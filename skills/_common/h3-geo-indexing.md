---
name: h3-geo-indexing
description: Uber H3 v4.4 hexagonal hierarchical geo indexing — resolution 0-15, kRing 이웃, polygonToCells, pentagon 12개 distortion, surge/dispatch 패턴
keywords: h3 geo-indexing hexagonal uber resolution kring polygonToCells cellToParent surge dispatch geofencing
intent: choose-h3-resolution index-coordinate query-neighbors derive-parent handle-pentagon-distortion migrate-v3-to-v4
paths:
patterns: H3Index latLngToCell cellToLatLng gridDisk cellToParent polygonToCells
requires: distributed-cache-decisions db-design
phase: plan implement review debug
tech-stack: any
min_score: 2
quality_axes_enforced: true
---

# H3 Geo Indexing (Uber, v4.4+)

> 핵심: H3는 icosahedron 위 aperture-7 hexagonal grid + 12 pentagon (resolution 마다). marketplace dispatch/surge에서 res 8-9 표준. 가장 흔한 사고는 **resolution mismatch join** (다른 res H3Index를 raw int64로 비교) + **pentagon 5-neighbor 가정 위반**.

## 의사결정 트리

### IF Resolution 결정 (Plan)
| 신호 | Resolution | Edge length |
|---|---|---|
| 대륙/국가 분석 | **0-3** | 1281 / 483 / 182 / 69 km |
| 도시 단위 분석 | **6-7** | 3.7 / 1.4 km |
| **marketplace dispatch + surge** | **8-9** | **531 / 201 m** |
| 도보 ETA / parking spot | **12-13** | 11 / 4 m |
| 미터 정밀도 | **14-15** | 1.5m / 0.5m |

원칙: 가장 fine한 res로 인덱싱 + `cellToParent`로 aggregation. 절대 mixed resolution join X.

### IF Coordinate → H3Index (Implement)
1. **v4 API**: `latLngToCell(lat, lng, res) → H3Index` (v3은 `geoToH3`)
2. 저장 — int64 (uint64) 컬럼 + B-Tree 인덱스
3. cluster — H3Index 자체가 prefix-coherent (가까운 위치는 numerically 가까움), 단 **계층 내부에서만**

### IF 이웃 검색 (Implement)
1. `gridDisk(h3, k) → cells` (v3 `kRing`)
2. unsafe variant — pentagon 만나면 error. default wrapper가 fallback to safe (slower)
3. capacity pre-allocation — `maxGridDiskSize(k)` 호출 후 array allocate
4. **pentagon은 5 neighbor** (hexagon은 6) — gridDisk 결과 수가 다름. assertion에 cell shape check

### IF Polygon 안 cell 찾기 (Implement)
1. v4: `polygonToCells(polygon, res) → cells` (v3 `polyfill`)
2. **centroid-based** — polygon 안에 cell 중심이 있으면 포함, boundary partial overlap은 제외
3. full coverage 필요 시 polygon buffer (e.g., 1 cell edge length 만큼 확장)
4. **antimeridian (±180°) 교차** polygon — 분할 또는 명시 winding. 미처리 시 empty/incorrect 결과

### IF v3 → v4 마이그레이션 (Plan)
| v3 | v4 |
|---|---|
| `geoToH3` | `latLngToCell` |
| `h3ToGeo` | `cellToLatLng` |
| `kRing` / `kRingDistances` | `gridDisk` / `gridDiskDistances` |
| `compact` / `uncompact` | `compactCells` / `uncompactCells` |
| `polyfill` | `polygonToCells` |

`h3-py>=4`, `h3-js>=4`, C lib `h3>=4` 동시 업그레이드. tutorial 2022 이전이면 거의 모두 v3.

### IF Hierarchical aggregation (Implement)
1. fine res에서 인덱싱 → `cellToParent(h3, parentRes)` 로 상위 aggregation
2. **재계산 금지** — index에서 parent 역도출, 좌표에서 다시 latLngToCell 하지 말 것
3. children — `cellToChildren(h3, childRes)` (1 hex → 7 child, 단 pentagon 제외)

## 가이드

- v4.4.1 (2025-11-12) stable, Apache 2.0. v4.4.0 (2025-11-07)에서 새 error code 추가
- 12 pentagon 위치 — icosahedron 12 vertex centered (대부분 ocean에 위치, land 영향 적음)
- distortion — pentagon 주변 cell area ~17% deviation. high-precision metric에서는 보정

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | resolution 별 edge length 결정적 (15 res 매트릭스) |
| 성능 효율성 | int64 H3Index가 lat/lng pair (16 bytes) 대비 절반 + 인덱싱 빠름 |
| 호환성 | C/Java/Python/JS/Go binding 모두 동일 spec |
| 사용성 | `latLngToCell` 1줄로 인덱싱 |
| 신뢰성 | pentagon error fallback safe variant 자동 |
| 보안 | location PII 마스킹은 fine res H3Index 노출 금지 (cell 좁으면 위치 식별) |
| 유지보수성 | v4 API 표준화 — v3 deprecate 절차 명확 |
| 이식성 | Apache 2.0, cloud 무관, Uber 외 DoorDash/Lyft/Airbnb/Foursquare 채택 |
| 확장성 | hierarchical resolution으로 zoom-level 별 aggregation 자동 |

## Gotchas

### Resolution mismatch join (raw int64 비교)
다른 res로 인덱싱한 H3Index는 numerically 호환 안 됨. 같은 위치라도 res 8 H3Index ≠ res 9 H3Index. join 전 `cellToParent`로 normalize 필수.

### Pentagon에서 6-neighbor 가정
`gridDisk(pentagon, 1)` 은 5 cells (pentagon 자체 제외). hex 가정 코드는 array bounds error. cell shape check (`isPentagon(h3)`) 또는 try-catch.

### `polygonToCells` boundary cell 제외
centroid 안 들어오는 boundary cell은 결과에서 빠짐. 완전 coverage 원하면 polygon buffer (~1 edge length).

### Antimeridian 교차 polygon
±180° longitude 가로지르는 polygon은 분할 또는 winding 명시. 미처리 시 empty 결과 — silent.

### v3 코드를 v4 환경에서 실행
2022 이전 tutorial은 거의 모두 v3 (`geoToH3`/`kRing`/`polyfill`). v4 환경에서 unresolved symbol. 마이그레이션 표 참조.

### Children 7개 가정 (pentagon은 6)
`cellToChildren(pentagon)` 은 6 child (1 hex 제외 + 5 child pentagon은 변종). 일반 hex는 7. 가정 코드 깨짐.

### Fine res H3Index를 PII 무방어로 노출
res 13-15는 ~4-1m precision — 사용자 위치 식별 가능. coarse res (8-9)로 marshal 또는 redaction.

## Source

- https://h3geo.org/docs/core-library/restable/ — resolution 0-15 별 average edge length (1281km → 0.000584km), 조회 2026-05-10
- https://h3geo.org/docs/core-library/overview/ — "exactly 12 pentagons at every resolution"; "impossible to tile the sphere/icosahedron completely with hexagons"; res 0 = 122 cells (110 hex + 12 pentagon), 조회 2026-05-10
- https://h3geo.org/docs/highlights/indexing — "every hexagonal cell ... has seven child cells" (aperture 7); "geographically close locations will tend to have numerically close indexes", 조회 2026-05-10
- https://h3geo.org/docs/library/migration-3.x/functions/ — v3 → v4 API rename 표 (geoToH3/kRing/polyfill 등), 조회 2026-05-10
- https://github.com/uber/h3/releases — v4.4.1 (2025-11-12), v4.4.0 (2025-11-07) new error codes, 조회 2026-05-10
- https://www.uber.com/blog/h3/ — "we calculate surge pricing by measuring supply and demand in hexagons"; "H3 as the grid system for analysis and optimization throughout our marketplaces", 조회 2026-05-10

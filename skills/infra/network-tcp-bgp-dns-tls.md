---
name: network-tcp-bgp-dns-tls
description: 네트워크 fundamentals — TCP congestion control, BGP routing, DNS resolution, TLS 1.3 handshake. CDN/peering 운영 시그널
keywords: tcp bgp dns tls cdn anycast bbr quic http3 cipher mtu peering
intent: design-cdn tune-tcp-congestion plan-bgp-peering choose-tls-version diagnose-mtu
paths:
patterns: tcp-bbr bgp anycast dns-resolver tls-1.3 quic http/3
requires: transport-reliability monitoring
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Network Fundamentals (TCP / BGP / DNS / TLS)

> 핵심: CDN 운영 / Open Connect 같은 edge 시스템은 **L3-7 전 계층의 동시 결정**이 필요. 한 계층 default(예: TCP cubic)가 다른 계층(예: 위성 RTT)과 안 맞으면 throughput이 절반 이하로. RFC 표준 위에서 결정.

## 의사결정 트리

### IF CDN/Edge node 신규 설계 (Plan)
1. anycast (BGP) — 동일 IP 다수 PoP에 광고, 라우팅이 가장 가까운 PoP 선택. unicast + DNS load balancing보다 latency↓
2. TCP congestion control — bulk transfer는 **BBR** (Google), 일반 web은 cubic. high-loss path는 BBRv2/v3
3. DNS — Anycast resolver(8.8.8.8 / 1.1.1.1 패턴). EDNS Client Subnet으로 클라이언트 위치 힌트 전달
4. TLS — **TLS 1.3 (RFC 8446)** 의무. 1.2 backward compat은 RFC 8996(TLS 1.0/1.1 deprecate)부터 정렬

### IF BGP peering 운영 (Implement|Review)
1. RPKI ROA 검증 — 자체 prefix를 ROA에 등록 + invalid 거부 정책 (RFC 6480-6483)
2. iBGP full-mesh 대안 — Route Reflector 또는 Confederation
3. BGP Communities로 traffic engineering — local-pref / MED 합의된 운영
4. **BGP hijack 모니터** — BGPmon/BGPstream 같은 외부 모니터링 + RPKI invalid 거부

### IF TLS 1.3 채택 (Implement)
1. cipher suite 선택 — TLS 1.3은 5개 권장 (`TLS_AES_256_GCM_SHA384`, `TLS_AES_128_GCM_SHA256`, `TLS_CHACHA20_POLY1305_SHA256`, etc.). 자율 선택 폭 ↓
2. 0-RTT (early data) — 재공격 위험 (replay), idempotent 요청만 허용
3. session resumption — PSK 기반, ticket 또는 session ID. forward secrecy 유지
4. ALPN — HTTP/2 또는 HTTP/3(QUIC) 협상

### IF MTU/MSS 문제 (Debug)
1. 증상: 큰 packet drop, small packet OK. p50 latency 정상이나 p99 spike
2. PMTUD 작동 확인 — ICMP type 3 code 4 차단 시 black hole. AWS/GCP에서 흔함
3. 조치 — `MSS clamping` (MTU - 40 for TCP/IPv4, MTU - 60 for IPv6) 라우터 설정
4. QUIC/HTTP3는 UDP 위 — PMTUD 자체 핸들링, 표준 MTU 1280 (IPv6 최소)

## 가이드

- TCP BBR 기본 활성: `sysctl net.ipv4.tcp_congestion_control=bbr` + `net.core.default_qdisc=fq`. Linux 4.9+.
- DNS resolver 캐시 TTL — 짧으면 traffic 폭주, 길면 failover slow. CDN은 보통 30-300초.
- TLS 1.3은 RTT 1회로 handshake — 1.2 대비 latency 절반. 0-RTT는 추가 절감이지만 보안 트레이드오프.

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | RFC 8446 (TLS 1.3) 준수로 표준 동작 보장 |
| 성능 효율성 | BBR으로 bulk throughput ↑, anycast로 latency ↓ |
| 호환성 | TLS 1.3은 fallback 메커니즘으로 1.2 client 수용 |
| 사용성 | sysctl 1줄로 BBR 활성 — 운영 부담↓ |
| 신뢰성 | RPKI invalid 거부로 BGP hijack 노출 시간 단축 |
| 보안 | TLS 1.0/1.1 deprecate (RFC 8996) — legacy 차단 |
| 유지보수성 | RFC 위주 인용 — 수십 년 안정 reference |
| 이식성 | TCP/BGP/DNS/TLS는 OS/벤더 무관 표준 |
| 확장성 | anycast PoP 추가는 BGP advertisement 1줄 |

## Gotchas

### PMTUD black hole (ICMP filter)
보안 정책이 ICMP 전부 drop → MTU 검출 실패. 큰 packet silent drop, 디버깅 매우 어려움. ICMP type 3 code 4(Fragmentation Needed)는 통과시켜야 함. 또는 MSS clamping.

### TLS 0-RTT replay 공격
early data는 재공격 가능. GET 같은 idempotent만 허용, POST는 거부. 명시 안 하면 결제 중복 같은 사고.

### BGP hijack 늦은 탐지
RPKI 미적용 시 invalid ROA prefix를 받아도 routing 그대로. 외부 BGP 모니터(BGPmon) + invalid 거부 정책 둘 다 필수.

### DNS resolver 캐시 TTL 너무 짧음
30초 미만이면 authoritative 폭주 + DDoS 표면. failover만 빠르길 원하면 health-check 기반 traffic 전환(GTM)으로 해결, TTL 짧게 유지하지 않는다.

### Cubic TCP를 high-loss path에 사용
cubic은 packet loss를 congestion으로 해석 → 무선/위성 path에서 throughput 폭락. BBR은 RTT 변화 기반이라 더 견고.

## Source

- https://datatracker.ietf.org/doc/html/rfc8446 — TLS 1.3 표준, 5 cipher suites, 1-RTT handshake, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/rfc8996 — TLS 1.0/1.1 deprecate (2021), 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/rfc4271 — BGP-4, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/rfc6480 — RPKI architecture for BGP origin validation, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/rfc9000 — QUIC transport (HTTP/3 기반), 조회 2026-05-10
- https://research.google/pubs/pub45646/ — Cardwell et al. "BBR: Congestion-Based Congestion Control" (2016), 조회 2026-05-10
- https://www.rfc-editor.org/rfc/rfc8201 — Path MTU Discovery for IPv6, ICMPv6 type 2 (Packet Too Big), 조회 2026-05-10

---
name: realtime-media-transport
description: Cloud gaming/streaming transport — QUIC/WebRTC, H.264/AV1 HW encode (NVENC), GCC congestion control, jitter buffer, NAT traversal
keywords: webrtc quic nvenc h264 av1 hevc gcc bbr jitter-buffer fec raptorq stun turn cloud-gaming
intent: design-realtime-transport choose-codec tune-jitter-buffer handle-nat-traversal disable-b-frames
paths:
patterns: webrtc quic nvenc h264 av1 GCC
requires: transport-reliability network-tcp-bgp-dns-tls
phase: plan implement review debug
tech-stack: any
min_score: 2
---

# Realtime Media Transport (Cloud Gaming / Streaming)

> 핵심: cloud gaming은 latency 우선 → **H.264 baseline + B-frame disable + NVENC ultra-low-latency**. video on-demand는 quality/bitrate 우선 → AV1/HEVC + B-frame 활용. 둘 결정이 다르다. transport는 TCP head-of-line blocking 차단 위해 UDP/QUIC.

## 의사결정 트리

### IF transport 프로토콜 (Plan)
| 신호 | 권장 |
|---|---|
| 양방향 인터랙티브 (cloud gaming, video call) | **WebRTC** (RTP/UDP + GCC) |
| HTTP/3 web app + datagram | **WebTransport** (W3C draft) |
| 일반 streaming/download | **QUIC** (RFC 9000) |
| 단순 DASH/HLS VOD | TCP + ABR 충분 |

### IF video codec 선택 (Plan)
| 워크로드 | 권장 |
|---|---|
| **Cloud gaming (sub-100ms glass-to-glass)** | H.264 baseline/main, **B-frame OFF**, NVENC ultra-low-latency preset |
| Live streaming (1-3s latency) | H.264/H.265 + low-latency tuning |
| VOD (bitrate 우선) | AV1 (royalty-free) 또는 HEVC |
| 모바일 호환 최우선 | H.264 (HW 디코더 보편) |

### IF B-frame 결정 (Implement)
1. **B-frame은 future frame 참조** → encode latency 1+ frame 추가
2. cloud gaming에는 absolute disable — `--bframes 0` (x264) 또는 NVENC `disableBFrames=1`
3. VOD는 B-frame 활용 — 압축률 ~10-15% 개선

### IF jitter buffer 튜닝 (Implement)
1. adaptive size — RTT + jitter 측정 기반 동적 조정
2. PLC (Packet Loss Concealment) — Opus 내장, video는 frame skip 또는 reference 재요청
3. FEC (RFC 6363) — 이중화 비용 vs loss 회복. RaptorQ (RFC 6330) for fountain coding

### IF congestion control (Implement)
1. **GCC (Google Congestion Control)** — WebRTC default, delay-based + loss-based hybrid (draft-ietf-rmcat-gcc)
2. **BBR (Google)** — bandwidth-delay product 모델. bulk throughput에는 좋으나 realtime 미디어에는 GCC 일반
3. cloud gaming은 GCC + sender-side bandwidth estimation (REMB/transport-cc)

### IF NAT traversal (Implement)
1. STUN (RFC 8489) — reflexive address discovery. 80% NAT 통과
2. TURN (RFC 8656) — symmetric NAT fallback (relay). 비용 발생
3. ICE — STUN + TURN candidate gathering + connectivity check

### IF HW acceleration 선택 (Implement)
| 플랫폼 | API |
|---|---|
| NVIDIA GPU | NVENC (Video Codec SDK) — H.264/HEVC/AV1 encode |
| Intel | VAAPI / Quick Sync |
| Apple | VideoToolbox |
| Android | MediaCodec NDK |

AV1 HW encode는 NVIDIA Ada (RTX 40+), Intel Arc, AMD RDNA3+ 부터.

## 가이드

- MTU — Ethernet 1500, IPv6 minimum 1280. UDP datagram이 path MTU 초과하면 fragmentation → loss 증폭
- A/V sync — RTP timestamps + RTCP Sender Reports로 clock alignment
- WebRTC SRTP — payload 암호화 + DTLS handshake 필수

## 9축 품질 체크

| 축 | 적용 |
|---|---|
| 기능 적합성 | NVENC ultra-low-latency preset이 cloud gaming spec 만족 |
| 성능 효율성 | UDP/QUIC로 head-of-line blocking 차단, FEC로 retransmit 회피 |
| 호환성 | H.264는 모든 디바이스 HW decode 보유 |
| 사용성 | WebRTC는 브라우저 native — install 0 |
| 신뢰성 | GCC adaptive bandwidth로 cellular 환경 안정 |
| 보안 | SRTP + DTLS로 E2E payload 암호화 |
| 유지보수성 | RFC 표준 (9000/8489/8656)으로 vendor 무관 |
| 이식성 | WebRTC native + browser 동일 stack |
| 확장성 | TURN 서버 horizontal scale + ICE candidate priority |

## Gotchas

### TCP-based transport에서 head-of-line blocking
한 packet loss가 모든 stream stall. cloud gaming/realtime에는 UDP/QUIC 강제.

### B-frame을 cloud gaming에 활성
encode latency 1+ frame 추가 → glass-to-glass 100ms 초과. NVENC `disableBFrames=1` 명시.

### MTU 초과 UDP datagram
path MTU 초과 시 IP fragmentation → 1 packet loss로 전체 frame loss. 1280-1400 byte 이하 권장.

### Symmetric NAT에 TURN 미설정
STUN만으로는 양방향 connectivity 불가. TURN relay 필수 — 비용 사전 계산.

### A/V sync drift 무방어
RTP timestamps만 의존하면 long-running session에서 누적. RTCP SR로 주기 alignment.

### AV1 HW encode 가정 후 구 GPU 배포
RTX 30 이전 / Intel 12세대 이전 / AMD RDNA2 이전은 AV1 HW encode 없음. fallback to H.265/H.264 명시.

## Source

- https://www.rfc-editor.org/rfc/rfc9000.html — QUIC Transport Protocol (UDP-based, multiplexed streams), 조회 2026-05-10
- https://www.rfc-editor.org/rfc/rfc8835.html — WebRTC transport architecture, 조회 2026-05-10
- https://www.rfc-editor.org/rfc/rfc8489.html — STUN reflexive address, 조회 2026-05-10
- https://www.rfc-editor.org/rfc/rfc8656.html — TURN relay, 조회 2026-05-10
- https://www.rfc-editor.org/rfc/rfc6330.html — RaptorQ FEC, 조회 2026-05-10
- https://datatracker.ietf.org/doc/html/draft-ietf-rmcat-gcc-02 — Google Congestion Control, 조회 2026-05-10
- https://developer.nvidia.com/video-codec-sdk — NVENC ultra-low-latency presets, AV1 encode (Ada+), 조회 2026-05-10
- https://aomediacodec.github.io/av1-spec/ — AV1 spec (royalty-free), 조회 2026-05-10

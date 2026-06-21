# {{프로젝트명}} PRD

> 작성일: {{YYYY-MM-DD}} | 버전: 1.0 | 작성자: {{작성자}}
> 마지막 검증: -

---

## Executive Summary

{{1~3문장으로 프로젝트를 설명: 누가 + 무엇을 + 왜}}

**핵심 목표**: {{기술적/비즈니스 핵심 달성 목표 1문장}}

**기술 스택**: {{주요 기술 스택 나열}}

**범위**: {{N개 도메인, M개 유저 스토리}}

---

## 문서 맵

| 문서 | 내용 | 읽는 사람 |
|------|------|----------|
| [context.md](context.md) | 문제 정의, 목표, 성공 지표, 페르소나, 범위 | 전체 |
| **도메인별 요구사항** | | |
| [domain/{{도메인1}}.md](domain/{{도메인1}}.md) | {{도메인1}} (US-0XX~0XX) | {{역할}} |
| [domain/{{도메인2}}.md](domain/{{도메인2}}.md) | {{도메인2}} (US-0XX~0XX) | {{역할}} |
| **시스템 설계** | | |
| [nfr.md](nfr.md) | 비기능 요구사항 (ISO 25010 기반) | Engineering |
| [architecture.md](architecture.md) | 이벤트/캐시/제약조건/역할 매트릭스 | Engineering |
| [risks.md](risks.md) | 리스크, 의존성, 거부된 대안 | 전체 |
| [glossary.md](glossary.md) | 용어 정의 | 전체 |
| [changelog.md](changelog.md) | 변경 이력 | 전체 |

---

## 기술 스택 요약

| 계층 | 기술 |
|------|------|
| Backend | {{예: Spring Boot 3.x + Gradle + Java 17+}} |
| Frontend | {{예: React 18 + TypeScript + Vite}} |
| DB | {{예: MySQL 5.7 (Docker)}} |
| Cache | {{예: Redis 7 (Docker)}} |
| Message | {{예: Kafka (Docker, KRaft)}} |
| Auth | {{예: JWT (Access 30min + Refresh 7d)}} |
| Test | {{예: JUnit 5 + Mockito + Playwright}} |

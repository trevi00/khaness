# {{프로젝트명}} 물리적 설계 (Physical Design)

> 선행: `logical.md` (정규화된 스키마)
> 파이프라인 7단계 산출물
> 3자 대조: ERD ↔ DDL ↔ 클래스 다이어그램

---

## 클래스 다이어그램

```mermaid
classDiagram
    class {{엔티티1}} {
        -Long id
        -{{타입}} {{필드}}
        +{{메서드}}()
    }
    class {{엔티티2}} {
        -Long id
        -{{타입}} {{필드}}
    }
    {{엔티티1}} "1" --> "*" {{엔티티2}} : contains
```

---

## DDL

### {{테이블명}}
```sql
-- MySQL 5.7 호환
CREATE TABLE {{테이블명}} (
    id           BIGINT        NOT NULL AUTO_INCREMENT,
    {{컬럼명}}    {{타입}}       {{NULL 여부}} {{DEFAULT}},
    created_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    {{INDEX/UNIQUE/FK 제약조건}}
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 3자 대조 검증 매트릭스

| ERD 엔티티 | DDL 테이블 | 클래스 | 속성 수 일치 | 관계 일치 | 타입 일치 |
|-----------|-----------|--------|------------|----------|----------|
| {{엔티티}} | {{테이블}} | {{클래스}} | {{Y/N}} | {{Y/N}} | {{Y/N}} |

---

## init 스크립트 구조

```
init/
├── 01-schema.sql    # CREATE TABLE (의존성 순서)
├── 02-index.sql     # CREATE INDEX
└── 03-seed.sql      # INSERT 초기 데이터
```

---

<!-- 검증 기준:
- ERD 엔티티 수 = DDL 테이블 수 = 클래스 수
- 각 엔티티의 속성 수 = 테이블 컬럼 수 = 클래스 필드 수
- ERD 관계 = FK 제약조건 = 클래스 참조
- 타입 호환: BIGINT↔Long, VARCHAR↔String, DECIMAL↔BigDecimal (MyBatis DTO/VO 매핑)
- 모든 CHECK 제약조건이 PRD 상태값과 일치
- init 스크립트 순서가 FK 의존성을 존중
-->

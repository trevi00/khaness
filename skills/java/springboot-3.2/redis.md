---
keywords: 레디스 redis Redis ACL acl 사용자 user 보안 인증 auth 세션 session Lettuce lettuce Jedis jedis spring-data-redis RedisConnectionFactory 캐시 cache TTL ttl pub/sub 클러스터 cluster sentinel Dockerfile dockerfile docker ElastiCache elasticache AWS aws EC2 ec2
intent: 레디스설정해 redis설정해 레디스유저만들어 ACL설정해 레디스보안설정해 레디스연결해 레디스도커만들어 엘라스티캐시설정해 캐시해 캐시만들어 레디스해
paths: src/main/resources/application.yml src/main/resources/application.properties config/redis docker/ redis/
patterns: spring-data-redis lettuce jedis RedisConnectionFactory RedisTemplate StringRedisTemplate LettuceConnectionFactory acl.conf redis.conf Dockerfile elasticache
requires: database security backend
phase: plan implement review
min_score: 2
---

# Redis Guide

## 의사결정 트리

### IF Redis 서버 사용자 생성 및 보안 설정 (Implement)
1. 현재 사용자 목록 확인
   ```
   acl list
   ```
2. 전용 사용자 생성 (default user 사용 금지)
   ```
   acl setuser <username> on ><password> allkeys allcommands
   ```
3. default user 비활성화
   ```
   acl setuser default off nopass ~* &* +@all
   ```
4. ACL 변경사항 영구 저장
   ```
   acl save
   ```
   - `acl save` 실패 시: redis.conf에 `aclfile /etc/redis/users.acl` 설정 확인
5. 접속 테스트 — No Auth로 접속 시 NOAUTH 에러 확인
6. **→ security 스킬: 비밀번호 강도, 네트워크 접근 제한 참고**

### IF Redis Docker 이미지 빌드 (Implement)
1. acl.conf 작성 — 사용자 정의 및 default 비활성화
   ```
   user <username> on ><password> allkeys allcommands
   user default off nopass ~* &* +@all
   ```
2. redis.conf 작성
   ```
   bind 0.0.0.0
   protected-mode yes
   port 6379
   aclfile /usr/local/etc/redis/acl.conf
   ```
3. Dockerfile 작성
   ```dockerfile
   FROM redis:latest
   # ACL 파일 복사
   COPY acl.conf /usr/local/etc/redis/acl.conf
   # Redis 구성 파일 복사
   COPY redis.conf /usr/local/etc/redis/redis.conf
   # CMD 지정
   CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]
   ```
4. 빌드 및 실행
   ```bash
   docker build -t my-redis .
   docker run -d --name redis -p 6379:6379 my-redis
   ```
5. 접속 테스트
   ```bash
   # default user → NOAUTH 에러 확인
   docker exec -it redis redis-cli
   > acl list
   (error) NOAUTH Authentication required.

   # 생성한 user로 인증 후 사용
   > auth <username> <password>
   OK
   > acl list
   ```

### IF Redis 보안 강화 (Implement)
1. `bind` 설정 (아래 redis.conf 설정 매트릭스 참고)
2. `protected-mode yes` 유지
3. `requirepass` 대신 ACL 사용 (Redis 6.0+)
4. 권한 최소화 — 애플리케이션 사용자에게 필요한 커맨드만 부여
   ```
   acl setuser appuser on ><password> ~app:* +get +set +del +expire +ttl +exists
   ```
5. 위험한 커맨드 비활성화 (운영 환경)
   ```
   rename-command FLUSHALL ""
   rename-command FLUSHDB ""
   rename-command CONFIG ""
   rename-command DEBUG ""
   ```
6. TLS 통신 적용 (민감 데이터 전송 시)

### IF Spring Boot Redis 연결 설정 (Implement)
1. application.yml 설정 (connection pool 포함)
   ```yaml
   spring:
     redis:
       database: '0'
       host: <redis-host>
       port: '6379'
       username: ${REDIS_USERNAME}
       password: ${REDIS_PASSWORD}
       timeout: '60000'
       lettuce:
         pool:
           max-active: 50       # 풀 최대 커넥션 수 (최대 200)
           max-idle: 50          # 최대 유휴 커넥션 수
           min-idle: 0           # 최소 유휴 커넥션 수
           time-between-eviction-runs-millis: 60000   # 유휴 커넥션 검사 주기(ms)
           min-evictable-idle-time-millis: 300000      # 유휴 최소 유지 시간(ms), 초과 시 제거
           test-on-borrow: true   # 커넥션 빌릴 때 유효성 검사
           test-while-idle: true  # 유휴 커넥션 유효성 검사
   ```
   - **pool 미설정 시**: 매 set/get 명령마다 새 커넥션 생성 → 성능 저하
   - `max-active`와 `max-idle`을 동일하게 설정하면 불필요한 커넥션 생성/폐기 방지
   - `test-on-borrow: true`는 네트워크 불안정 환경에서 stale 커넥션 방지에 유용
2. RedisConnectionFactory 커스텀 설정 (인증 포함)
   ```java
   @Configuration
   public class RedisConfig {
       @Bean
       public RedisConnectionFactory redisConnectionFactory(
               @Value("${spring.redis.host}") String host,
               @Value("${spring.redis.port}") int port,
               @Value("${spring.redis.username}") String username,
               @Value("${spring.redis.password}") String password) {
           RedisStandaloneConfiguration config = new RedisStandaloneConfiguration();
           config.setHostName(host);
           config.setPort(port);
           config.setUsername(username);
           config.setPassword(RedisPassword.of(password));
           return new LettuceConnectionFactory(config);
       }
   }
   ```
3. password/username을 application.yml에 평문으로 두지 말 것 — 환경변수 또는 Vault 사용

### IF AWS ElastiCache Redis 연결 (Implement)
1. EC2에서 redis-cli 설치 (Amazon Linux / RHEL 기반)
   ```bash
   sudo yum install gcc wget -y
   sudo mkdir -p /opt/Redis && cd /opt/Redis
   sudo wget http://download.redis.io/redis-stable.tar.gz
   sudo tar xvzf redis-stable.tar.gz
   cd redis-stable
   make distclean && make
   sudo cp src/redis-cli /usr/bin/
   ```
2. ElastiCache 엔드포인트로 접속 테스트
   ```bash
   redis-cli -h <elasticache-endpoint>
   # 예: redis-cli -h osp-redis.74olth.clustercfg.apn2.cache.amazonaws.com
   ```
3. ACL 인증이 설정된 경우
   ```bash
   redis-cli -h <elasticache-endpoint> --user <username> --pass <password>
   ```
4. Spring Boot application.yml에서 host를 ElastiCache 엔드포인트로 지정
   ```yaml
   spring:
     redis:
       host: <elasticache-endpoint>
       port: '6379'
       username: ${REDIS_USERNAME}
       password: ${REDIS_PASSWORD}
   ```
5. **주의사항**
   - ElastiCache는 VPC 내부에서만 접근 가능 — EC2와 같은 VPC/서브넷 또는 VPC 피어링 필요
   - 로컬 개발 환경에서 직접 접근 불가 — SSH 터널 또는 VPN 사용
   - 클러스터 모드 사용 시 `clustercfg` 엔드포인트 사용, Lettuce는 클러스터 모드 자동 지원

### IF Redis 보안 리뷰 (Review)
- [ ] default user가 비활성화되어 있는가
- [ ] 전용 사용자가 ACL로 생성되어 있는가
- [ ] 비밀번호가 소스코드/yml에 평문으로 노출되어 있지 않은가 (환경변수/Vault 사용)
- [ ] `bind`가 `0.0.0.0`으로 열려있지 않은가
- [ ] `protected-mode`가 `yes`인가
- [ ] FLUSHALL, CONFIG 등 위험 커맨드가 rename 또는 비활성화되어 있는가
- [ ] 애플리케이션 사용자 권한이 최소화되어 있는가 (allcommands 지양)
- [ ] Redis 접속 정보가 .gitignore 대상 파일에만 있는가

## 가이드

### redis.conf — bind / protected-mode 동작 매트릭스
| protected-mode | bind 설정 | 접속 가능 범위 |
|:-:|:-:|:-:|
| yes | 지정됨 (예: `0.0.0.0`) | 지정된 IP의 네트워크 인터페이스로만 접속 |
| yes | 미지정 (주석 처리) | `127.0.0.1` (로컬)만 접속 가능 |
| no | 지정됨 | 지정된 IP만 접속 가능 |
| no | 미지정 | **모든 IP 접속 가능 (위험)** |

- `bind`는 **서버의 네트워크 인터페이스 IP**를 의미 (클라이언트 IP가 아님). `ifconfig`/`ip addr`로 확인되는 IP 중 통신에 사용되는 것을 지정
- `bind`는 최대 16개 IP 지정 가능
- `bind 0.0.0.0`은 모든 인터페이스에서 수신 — Docker 컨테이너 내부에서는 일반적으로 사용하되, 호스트 네트워크 모드에서는 주의

### ACL 사용자 권한 설계 패턴
| 역할 | 권한 예시 | 용도 |
|------|----------|------|
| admin | `allkeys allcommands` | 관리/운영 (운영자만) |
| appuser | `~app:* +get +set +del +expire` | 애플리케이션 일반 사용 |
| readonly | `~* +get +mget +keys +scan` | 모니터링/조회 전용 |
| session | `~session:* +get +set +del +expire` | 세션 저장 전용 |

### redis.conf vs 런타임 ACL
- `acl setuser`는 런타임 설정 → 재시작하면 날아감
- 반드시 `acl save`로 파일에 저장하거나, redis.conf / users.acl에 직접 기술
- Docker 환경: volume으로 acl 파일 마운트 필수

### Lettuce Connection Pool 파라미터 가이드
| 파라미터 | 설명 | 권장값 |
|----------|------|--------|
| `max-active` | 풀 최대 커넥션 수 (최대 200) | 50 |
| `max-idle` | 최대 유휴 커넥션 수 | max-active와 동일 |
| `min-idle` | 최소 유휴 커넥션 수 | 0 (저사양) ~ 10 (고트래픽) |
| `time-between-eviction-runs-millis` | 유휴 커넥션 검사/제거 주기 | 60000 (1분) |
| `min-evictable-idle-time-millis` | 유휴 최소 유지 시간, 초과 시 제거 | 300000 (5분) |
| `test-on-borrow` | 빌릴 때 커넥션 유효성 검사 | true |
| `test-while-idle` | 유휴 검사 시 유효성 확인 | true |

- pool 미설정 시 매 명령마다 새 커넥션 생성 — 반드시 설정할 것
- `max-active` = `max-idle`로 맞추면 풀 크기가 안정적으로 유지됨
- `test-on-borrow`는 약간의 오버헤드가 있으나, stale 커넥션으로 인한 에러 방지에 효과적

### Spring Boot에서 username 지원
- `spring.redis.username`은 Spring Boot 2.6+ / spring-data-redis 2.6+ 에서 지원
- 이전 버전에서는 RedisConnectionFactory를 직접 빈으로 등록하여 username 설정

## Gotchas

### acl save 누락
`acl setuser`로 사용자를 만들고 `acl save`를 잊으면, Redis 재시작 시 사용자가 사라짐. Docker 환경에서 특히 주의 — 컨테이너 재생성 시 모든 설정 초기화.

### default user 비활성화 후 잠김
default user를 `off`로 만든 뒤 새 사용자 인증 정보를 잊으면 Redis 접속 불가. 반드시 새 사용자로 접속 가능한 것을 확인한 후 default를 비활성화할 것.

### Lettuce vs Jedis 인증 차이
Lettuce(기본)는 AUTH username password를 자동 전송. Jedis는 버전에 따라 username 파라미터를 지원하지 않을 수 있음 — Jedis 3.x 이상에서만 ACL username 지원.

### Dockerfile에서 sed로 redis.conf 수정 시 주의
redis.conf를 COPY한 뒤 `sed`로 수정하는 패턴은 유지보수가 어렵고 실수 여지가 큼. 가능하면 완성된 redis.conf를 직접 COPY하는 것이 안전. `sed` 사용 시 정규식 이스케이프 (`/` → `\/`) 주의.

### Docker 컨테이너 내 bind 0.0.0.0
Docker 컨테이너 내부에서 `bind 127.0.0.1`로 설정하면 컨테이너 외부(호스트)에서 접근 불가. 컨테이너 환경에서는 `bind 0.0.0.0` + 포트 매핑(`-p 6379:6379`)이 일반적. 보안은 Docker 네트워크 레벨에서 제어.

### EC2에서 redis-cli 설치 시 make 실패
`gcc`가 없으면 `make` 실패. 반드시 `yum install gcc` 먼저. Amazon Linux 2023에서는 `dnf install gcc`를 사용.

### ElastiCache 로컬 접근 불가
ElastiCache는 VPC 내부 전용. 로컬 PC에서 직접 `redis-cli -h <endpoint>`는 불가. SSH 터널(`ssh -L 6379:<endpoint>:6379 ec2-user@bastion`)이나 VPN으로 우회.

### ElastiCache 클러스터 모드 엔드포인트
클러스터 모드 시 `clustercfg` 포함된 Configuration Endpoint 사용. 개별 노드 엔드포인트로 접속하면 MOVED 에러 발생. Spring Boot Lettuce는 `spring.redis.cluster.nodes`로 설정.

### MISCONF — RDB 스냅샷 실패로 Write 거부
**에러**: `RedisCommandExecutionException: MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk.`
**원인**: BGSAVE(RDB 스냅샷)가 실패하면 `stop-writes-on-bgsave-error yes`(기본값) 설정에 의해 모든 쓰기 명령이 거부됨. 디스크 공간 부족, 권한 문제, dump.rdb 파일 손상 등이 원인.
**즉시 해결**:
```bash
# redis-cli 접속 후
config set stop-writes-on-bgsave-error no
```
**근본 해결**:
1. 디스크 공간 확인 (`df -h`) → 부족하면 확보
2. `/data` 디렉토리 권한 확인 (`ls -la /data`)
3. 기존 dump.rdb 복구 필요 시:
   ```bash
   docker cp redis:/data .          # dump.rdb 호스트로 복사
   docker run -d --name redis -p 6379:6379 \
     -v /path/to/data:/data redis   # 볼륨 마운트로 재시작
   ```
4. redis.conf에 영구 설정:
   ```
   stop-writes-on-bgsave-error no
   ```
**주의**: `stop-writes-on-bgsave-error no`는 응급 조치. RDB 실패 원인을 반드시 해결할 것 — 그렇지 않으면 데이터 유실 위험.

### 환경별 Redis 설정 분리 안 함
개발 환경에서 `requirepass` 없이 쓰다가 운영에서 인증 실패. application-{profile}.yml로 환경별 분리하고, 운영 프로파일에는 반드시 인증 정보 포함.

### Docker Redis ACL 파일 마운트
```yaml
# docker-compose.yml
services:
  redis:
    image: redis:6
    command: redis-server /usr/local/etc/redis/redis.conf
    volumes:
      - ./redis/redis.conf:/usr/local/etc/redis/redis.conf
      - ./redis/users.acl:/usr/local/etc/redis/users.acl
      - redis-data:/data
```
redis.conf에 `aclfile /usr/local/etc/redis/users.acl` 지정 필수.

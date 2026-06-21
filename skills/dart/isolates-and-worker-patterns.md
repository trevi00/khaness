---
keywords: dart 3.11 isolate Isolate.run Isolate.spawn ReceivePort SendPort worker request response port lifecycle 격리 워커 메시지 패싱 백그라운드
intent: dart isolate 설계 one-shot run vs long-lived spawn worker request-response port 생명주기 안전 종료
paths: lib/src/workers/ lib/src/isolates/
patterns: Isolate.run Isolate.spawn ReceivePort SendPort port.listen close() top-level entry function
requires: dart
phase: design implement review
tech-stack: dart
min_score: 3
---

# Dart 3.11.x Isolates + Worker Patterns

> 핵심 원칙: **isolate는 메모리를 공유하지 않고 메시지로만 통신**한다. 한 번 쓰는 계산은 `Isolate.run`, 오래 사는 worker는 `Isolate.spawn` + `ReceivePort/SendPort` + 명시적 종료. closure 캡처는 위험 → top-level 또는 static entry.

## 의사결정 트리

### IF 무거운 계산 한 번 (Implement)
- `Isolate.run(() => heavyComputation())` — 끝
- 결과 1개, 자동 종료, port 관리 X
- main isolate 블로킹 X (UI 응답성 보존)

### IF 오래 사는 worker (Design)
- `Isolate.spawn(workerEntry, mainPort)` — 명시적 protocol
- 시나리오: 큰 파일 파싱 stream, 여러 요청 처리, 백그라운드 작업
- protocol 결정 필요:
  - 1-shot vs request-response vs streaming
  - request id로 응답 매칭
  - cancel / shutdown 신호

### IF entry function 작성 (Implement)
1. **top-level 또는 static 함수만** — closure 캡처 금지 (docs warn)
2. 메시지는 JSON-safe (Map, List, primitive) 또는 transferable
3. shared mutable state 가정 X — 항상 사본

### IF port 누수 / hang (Review)
1. `ReceivePort.close()` 호출되는가
2. `Isolate.exit` 또는 `Isolate.kill`로 종료되는가
3. main이 요청 보냈는데 worker가 죽었으면 reply 영원히 안 옴 → timeout
4. request id 없으면 응답 매칭 불가

## one-shot: `Isolate.run`

```dart
import 'dart:convert';
import 'dart:isolate';

Future<int> totalScore(String jsonText) {
  return Isolate.run(() {
    final decoded = jsonDecode(jsonText) as List<dynamic>;
    return decoded
        .cast<Map<String, dynamic>>()
        .map((row) => row['score'] as int)
        .fold(0, (a, b) => a + b);
  });
}

void main() async {
  final raw = await File('large.json').readAsString();
  final total = await totalScore(raw);  // main 안 막힘
  print(total);
}
```
**장점**: boilerplate 없음. **제약**: 1번만, 매번 isolate spawn 비용.

## long-lived worker: `Isolate.spawn`

### 기본 셋업 (top-level entry)
```dart
import 'dart:async';
import 'dart:isolate';

// IMPORTANT: top-level (또는 static) — closure capture 금지
void _workerEntry(SendPort mainPort) {
  final commands = ReceivePort();
  mainPort.send(commands.sendPort);  // worker → main: send port 알려줌

  commands.listen((message) {
    if (message is _ShutdownSignal) {
      commands.close();
      Isolate.exit();
    }
    if (message is _Request) {
      try {
        final result = _doWork(message.payload);
        message.replyPort.send(_Response(message.id, result, error: null));
      } catch (e, st) {
        message.replyPort.send(_Response(message.id, null, error: '$e\n$st'));
      }
    }
  });
}

int _doWork(int input) {
  // CPU-intensive
  var sum = 0;
  for (var i = 0; i < input; i++) sum += i;
  return sum;
}
```

### Request/Response 메시지
```dart
class _Request {
  _Request(this.id, this.payload, this.replyPort);
  final int id;
  final int payload;
  final SendPort replyPort;
}

class _Response {
  _Response(this.id, this.value, {this.error});
  final int id;
  final int? value;
  final String? error;
}

class _ShutdownSignal {}
```

### Main isolate orchestrator
```dart
class Worker {
  Worker._(this._sendPort, this._isolate);

  final SendPort _sendPort;
  final Isolate _isolate;
  final _pending = <int, Completer<int>>{};
  var _nextId = 0;

  static Future<Worker> start() async {
    final initPort = ReceivePort();
    final isolate = await Isolate.spawn(_workerEntry, initPort.sendPort);
    final sendPort = await initPort.first as SendPort;
    initPort.close();
    final w = Worker._(sendPort, isolate);
    return w;
  }

  Future<int> compute(int input) {
    final id = _nextId++;
    final reply = ReceivePort();
    final completer = Completer<int>();
    _pending[id] = completer;

    reply.first.then((msg) {
      reply.close();
      final res = msg as _Response;
      _pending.remove(id);
      if (res.error != null) {
        completer.completeError(StateError(res.error!));
      } else {
        completer.complete(res.value!);
      }
    });

    _sendPort.send(_Request(id, input, reply.sendPort));
    return completer.future.timeout(
      const Duration(seconds: 10),
      onTimeout: () {
        _pending.remove(id);
        reply.close();
        throw TimeoutException('worker timeout for id=$id');
      },
    );
  }

  Future<void> shutdown() async {
    _sendPort.send(_ShutdownSignal());
    // 또는 강제: _isolate.kill(priority: Isolate.immediate);
  }
}

// 사용
void main() async {
  final w = await Worker.start();
  final r = await w.compute(1000000);
  print(r);
  await w.shutdown();
}
```

## protocol 옵션 매트릭스

| 시나리오 | 패턴 | 메모 |
|---|---|---|
| 한 번만 무거운 계산 | `Isolate.run` | 가장 단순 |
| 같은 작업 여러 번 | spawn + request id | id로 응답 매칭 |
| stream 결과 (예: line-by-line 파싱) | reply port를 1회 first 대신 listen | 종료 메시지 정의 |
| broadcast event source | spawn + main의 broadcast Stream으로 fan-out | listener 관리 |

## 5축 품질 체크

| 축 | 체크 |
|---|---|
| 정확성 | entry function이 top-level 또는 static인가 (closure 캡처 X) |
| 안전성 | ReceivePort.close()와 Isolate 종료가 명시적인가 (누수 차단) |
| 성능 | one-shot 작업에 spawn 대신 Isolate.run을 쓰는가 |
| 가독성 | request id + reply port 패턴이 명확한가 |
| 검증성 | timeout 매핑 + error 메시지가 main으로 전달되는가 |

## Gotchas

### closure capture로 spawn entry 작성
```dart
final localData = [1,2,3];
Isolate.spawn((SendPort p) {
  // localData 캡처 → 큰 객체 직렬화 / hidden state 위험
}, mainPort);
```
docs 경고. top-level / static 함수로.

### `Isolate.run` 안에서 main isolate 객체 사용
파라미터로 안 넘긴 외부 변수는 capture될 수 있음. 가능하면 단순 input만 넘기기.

### ReceivePort.close() 누락
worker가 reply port 닫지 않으면 main의 listener가 hold → memory leak. 응답 후 항상 close.

### request id 없이 응답 매칭
여러 요청 동시 보내면 어떤 응답이 어디로 가야 할지 모름. id + Map<id, Completer> 패턴.

### worker가 throw → main이 무한 대기
catch해서 error response 보내거나, Isolate.spawn의 `errorsAreFatal`/`onError` 옵션 사용.

### `Isolate.kill`을 정상 종료에 사용
data corruption, 진행 중인 작업 손실. shutdown 메시지 → worker가 정리 → `Isolate.exit`.

### 비-JSON-safe 객체 전송
일부 객체(socket, database connection)는 transfer 불가 → 에러. transfer 가능한 형태로 직렬화.

### timeout 없이 await reply
worker hang 시 main도 무한 대기. 항상 `.timeout(...)`으로 boundary.

### `Isolate.run`을 매 호출마다 spawn
비싸다. 핫 path면 long-lived worker로.

### main port에 listener 둘이 등록
ReceivePort는 single subscription. broadcast 필요하면 `.asBroadcastStream()`.

## 도구 사용 패턴 (Harness)
- closure spawn 탐지: `Grep("Isolate\\.spawn\\([^,]*\\([^)]*\\)\\s*\\{", glob="lib/**/*.dart")` (lambda 형태)
- close 누락: `Grep("ReceivePort\\(\\)", glob="lib/**/*.dart")` 와 `\.close\(\)` 매칭
- timeout 누락: `Grep("await .*\\.first|await .*completer\\.future", glob="lib/**/*.dart")` 후 `.timeout` 동행 여부
- shutdown signal 패턴: `Grep("ShutdownSignal|_workerEntry", glob="lib/**/*.dart")`
- one-shot 적합 케이스: `Grep("Isolate\\.spawn", glob="lib/**/*.dart")` 후 use site가 1회성이면 run으로 권장

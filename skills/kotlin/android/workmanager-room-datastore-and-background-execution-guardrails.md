---
name: workmanager-room-datastore-and-background-execution-guardrails
description: Android에서 WorkManager 백그라운드 작업, Room DB 트랜잭션·마이그레이션, DataStore preference/proto 경계를 라인 코드로 강제.
keywords: android workmanager work-request room dao migration entity transaction datastore preferencedatastore protodatastore foreground-service expedited periodic work-request constraints unique-work backgroundtask deferrable doze app-standby battery-bucket exact-alarm background-fetch sqlite-wal flow stateflow 백그라운드 워크매니저 룸 데이터스토어
intent: 만들어 추가해 구현해 마이그레이션 스케줄해 저장해 동기화
paths: app/src/main/kotlin app/src/main/java app/schemas/ app/src/main/AndroidManifest.xml
patterns: WorkManager OneTimeWorkRequestBuilder PeriodicWorkRequestBuilder Constraints CoroutineWorker Worker setForeground ForegroundInfo enqueueUniqueWork ExistingWorkPolicy KEEP REPLACE APPEND ExpeditedWorkPolicy RUN_AS_NON_EXPEDITED_WORK_REQUEST OutOfQuotaPolicy Room @Database @Entity @Dao @Query @Transaction Migration AutoMigration RoomDatabase.Builder fallbackToDestructiveMigration enableMultiInstanceInvalidation DataStore preferencesDataStore stringPreferencesKey edit Preferences MutablePreferences Flow first
requires:
phase: plan implement review debug migrate
tech-stack: kotlin
min_score: 2
---

# Android — WorkManager / Room / DataStore Background Execution Guardrails

Android에서 백그라운드 / 영속성 코드는 OS의 강한 제약 (Doze, App Standby, Background Execution Limits, Foreground Service 분류, Storage Access Framework) 안에서만 동작한다. WorkManager / Room / DataStore는 그 제약을 다루는 표준 도구지만 **계약 (constraints, unique work, transaction, migration)**을 코드 라인 수준에서 강제하지 않으면 "백그라운드에서 안 돌아요" / "DB 마이그레이션 깨졌어요" / "preference 안 저장돼요" 류 incident가 발생한다. 이 스킬은 그 계약을 라인 단위로 강제한다.

## 의사결정 트리

### IF 백그라운드 작업 필요 (Plan)
1. **deferrable + 안정성 보장 = WorkManager.** 즉시 실행 / 정밀 타이밍 / 짧은 작업이면 다른 것.
2. **즉시 + 짧음 (< 몇 초)** → coroutine + viewModelScope. WorkManager 과한 도구.
3. **사용자 인지 + 즉시 + 길음** → ForegroundService (또는 expedited Work).
4. **정확한 시각 트리거 (알람 시계)** → AlarmManager (`SCHEDULE_EXACT_ALARM` permission). WorkManager 부적합.
5. **앱 종료 후에도 보장** → WorkManager가 유일한 신뢰 가능한 옵션 (JobScheduler/AlarmManager wrap).

### IF WorkManager Work 정의 (Implement)
1. **`CoroutineWorker` 우선**. blocking `Worker`는 신규 코드에서 회피.
2. **`OneTimeWorkRequestBuilder` vs `PeriodicWorkRequestBuilder`** — 주기 ≥ 15분만 `Periodic`.
3. **Constraints 필수 명시** — 네트워크, 충전, 배터리 not-low, 저장공간 OK 등. constraint 없으면 OS가 임의로 결정.
4. **expedited work** — Android 12+에서 즉시 시작이 필요할 때. quota 제한 있음. `setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)`로 fallback.
5. **`enqueueUniqueWork`** — 같은 작업이 2번 큐잉되는 사고 방지. 정책: `KEEP` (이미 있으면 무시), `REPLACE` (취소+새로), `APPEND` (꼬리에 붙임).
6. **input/output Data 크기 제한 10KB** — 큰 데이터는 file/DB 거쳐 reference만 전달.
7. **재시도 정책** — `Result.retry()` + `setBackoffCriteria`. 무한 재시도 금지 — 명시적 `runAttemptCount` 한도.

### IF foreground 알림 필요한 long Work (Implement)
1. `setForeground(ForegroundInfo(...))` 호출 — Notification + service type 명시 (Android 14+ 필수).
2. **Manifest `android:foregroundServiceType`** 정확히 매칭 (`dataSync`, `mediaPlayback`, ...). 안 맞으면 launch 실패.
3. background → foreground 승격 시점 user-perceptible 보장.

### IF Room schema 설계 (Implement)
1. **`@Database(version = N, exportSchema = true)`** + `app/schemas/` 경로 git에 commit. AutoMigration을 위한 사전조건.
2. **`@PrimaryKey(autoGenerate = true)`** 또는 명시 PK. composite PK는 `primaryKeys = ["a", "b"]`.
3. **외래 관계** — `@ForeignKey` + index. cascade는 명시적으로.
4. **인덱스** — 자주 WHERE/JOIN하는 컬럼에 `@Entity(indices = [Index("user_id")])`.
5. **DateTime / Enum** — `@TypeConverter`로 명시 타입 매핑.

### IF Room 쿼리 / DAO (Implement)
1. **suspend `@Query`** — coroutine 친화. 또는 Flow 반환 (자동 invalidation).
2. **여러 statement 묶음** → `@Transaction` 메서드. 부분 실패 시 rollback.
3. **`@RawQuery`** 신중. injection 위험 — 외부 입력은 SimpleSQLiteQuery에 bind.
4. **`onConflict = OnConflictStrategy.REPLACE`** — UPSERT 의도일 때만. 다른 경우 IGNORE/ABORT.
5. **`LIMIT` 없는 SELECT** 금지 — 큰 테이블에서 OOM.

### IF Room 마이그레이션 (Migrate)
1. **`fallbackToDestructiveMigration()` 신규 코드 금지** — 사용자 데이터 날려버림.
2. **AutoMigration 우선** (Room 2.4+). 단순 컬럼 추가/삭제는 `@AutoMigration`. spec class로 rename/delete handle.
3. **복잡 변경** → 수동 `Migration` object — `database.execSQL("ALTER TABLE ...")`. 모든 SQL 명시.
4. **migration test** — `MigrationTestHelper`로 ver N → N+1 데이터 보존 검증. CI 필수.
5. **schema JSON commit** — diff review 가능. PR에서 schema 변경이 의도한 변경인지 확인.

### IF DataStore 선택 (Plan)
1. **Preferences DataStore** — key-value. 작은 설정값 (theme, lastSyncMs, userId).
2. **Proto DataStore** — 구조화 데이터 + type safety. 복잡 설정 / multi-field.
3. **SharedPreferences는 신규 코드에서 회피** — 동기 disk I/O, runtime corruption 가능.
4. **DB 대용으로 DataStore 사용 금지** — 검색/정렬/관계 → Room.

### IF DataStore 사용 (Implement)
1. **top-level singleton** — `val Context.dataStore by preferencesDataStore(name = "settings")`. ViewModel 안에서 만들지 말 것.
2. **Flow로 read** — collect/first 사용. blocking get 없음 (의도적).
3. **`edit { }` 안에서만 write** — atomic. partial update 안전.
4. **Migration** — proto schema 변경 시 `produceMigrations` 등록. preference→proto 마이그레이션도 동일 메커니즘.
5. **중복 DataStore 인스턴스 금지** — 같은 name으로 두 번 생성 시 throw.

### IF 코드 리뷰 (Review)
- [ ] WorkManager 사용 적합성 (deferrable + 보장) 확인
- [ ] Constraints 명시 (network/battery/storage)
- [ ] enqueueUniqueWork + ExistingWorkPolicy 적합
- [ ] CoroutineWorker 사용 (blocking Worker 회피)
- [ ] expedited Work에 OutOfQuotaPolicy fallback
- [ ] Foreground Work에 service type Manifest 일치
- [ ] input Data 10KB 이하
- [ ] Room exportSchema = true + schemas/ commit
- [ ] AutoMigration 또는 명시 Migration + test
- [ ] fallbackToDestructiveMigration 사용 안 함
- [ ] DAO suspend 또는 Flow 반환
- [ ] DataStore singleton + Flow 기반 read
- [ ] SharedPreferences 신규 코드에 도입 안 됨

## 핵심 패턴

### WorkManager — 동기 Worker
```kotlin
class SyncWorker(
    appContext: Context,
    params: WorkerParameters,
    private val syncRepo: SyncRepository,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            if (runAttemptCount >= MAX_RETRIES) return@withContext Result.failure()
            val targetId = inputData.getLong(KEY_TARGET_ID, -1L)
            require(targetId > 0) { "missing target id" }
            syncRepo.sync(targetId)
            Result.success()
        } catch (e: IOException) {
            Result.retry()                  // backoff 적용됨
        } catch (e: CancellationException) {
            throw e                         // 취소 전파
        } catch (e: Exception) {
            Result.failure()                // 영구 실패
        }
    }

    companion object {
        const val KEY_TARGET_ID = "target_id"
        private const val MAX_RETRIES = 5
    }
}
```

### WorkRequest 빌드 + Constraints + UniqueWork
```kotlin
val constraints = Constraints.Builder()
    .setRequiredNetworkType(NetworkType.CONNECTED)
    .setRequiresBatteryNotLow(true)
    .setRequiresStorageNotLow(true)
    .build()

val request = OneTimeWorkRequestBuilder<SyncWorker>()
    .setConstraints(constraints)
    .setInputData(workDataOf(SyncWorker.KEY_TARGET_ID to targetId))
    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
    .addTag("sync:$targetId")
    .build()

WorkManager.getInstance(context).enqueueUniqueWork(
    "sync-$targetId",
    ExistingWorkPolicy.KEEP,                // 이미 큐잉되어 있으면 그대로 둠
    request,
)
```

### Periodic Work + Flex
```kotlin
val periodic = PeriodicWorkRequestBuilder<HeartbeatWorker>(
    repeatInterval = 30, repeatIntervalTimeUnit = TimeUnit.MINUTES,
    flexTimeInterval = 10, flexTimeIntervalUnit = TimeUnit.MINUTES,
)
    .setConstraints(constraints)
    .build()

WorkManager.getInstance(context).enqueueUniquePeriodicWork(
    "heartbeat",
    ExistingPeriodicWorkPolicy.KEEP,
    periodic,
)
```

### Expedited + Fallback
```kotlin
val urgent = OneTimeWorkRequestBuilder<NotifyWorker>()
    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
    .setConstraints(Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build())
    .build()
```

### Foreground Worker (오래 걸리는 작업)
```kotlin
class ImportWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        setForeground(createForegroundInfo("Importing..."))
        return runImport()
    }

    private fun createForegroundInfo(text: String): ForegroundInfo {
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("Sync")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_sync)
            .setOngoing(true)
            .build()
        return ForegroundInfo(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    }
}
```
```xml
<!-- AndroidManifest.xml -->
<service
    android:name="androidx.work.impl.foreground.SystemForegroundService"
    android:foregroundServiceType="dataSync"
    tools:node="merge" />
```

### Room — Database + DAO + Migration
```kotlin
@Database(
    entities = [CartEntity::class, OrderEntity::class],
    version = 3,
    exportSchema = true,
    autoMigrations = [
        AutoMigration(from = 1, to = 2),
        AutoMigration(from = 2, to = 3, spec = AppDatabase.Mig2to3::class),
    ],
)
@TypeConverters(InstantConverter::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun cartDao(): CartDao

    @RenameColumn(tableName = "orders", fromColumnName = "amt", toColumnName = "amount_cents")
    class Mig2to3 : AutoMigrationSpec
}
```
```kotlin
@Dao
interface CartDao {
    @Query("SELECT * FROM cart WHERE user_id = :userId LIMIT 50")
    fun observeByUser(userId: Long): Flow<List<CartEntity>>

    @Transaction
    @Query("SELECT * FROM cart WHERE id = :id")
    suspend fun cartWithItems(id: Long): CartWithItems?

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertOrIgnore(entity: CartEntity): Long

    @Update
    suspend fun update(entity: CartEntity)

    @Query("DELETE FROM cart WHERE id = :id")
    suspend fun delete(id: Long): Int
}
```

### Manual Migration (복잡 케이스)
```kotlin
val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE cart_new (id INTEGER PRIMARY KEY NOT NULL, user_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL DEFAULT 0)")
        db.execSQL("INSERT INTO cart_new (id, user_id, amount_cents) SELECT id, user_id, COALESCE(amount_cents, 0) FROM cart")
        db.execSQL("DROP TABLE cart")
        db.execSQL("ALTER TABLE cart_new RENAME TO cart")
        db.execSQL("CREATE INDEX index_cart_user_id ON cart(user_id)")
    }
}

Room.databaseBuilder(ctx, AppDatabase::class.java, "app.db")
    .addMigrations(MIGRATION_3_4)
    // .fallbackToDestructiveMigration()    ← 사용 금지
    .build()
```

### Migration test
```kotlin
@get:Rule
val helper = MigrationTestHelper(
    InstrumentationRegistry.getInstrumentation(),
    AppDatabase::class.java,
)

@Test
fun migrate3to4_preservesAmount() {
    helper.createDatabase(TEST_DB, 3).use { db ->
        db.execSQL("INSERT INTO cart (id, user_id, amount_cents) VALUES (1, 100, 4500)")
    }
    val migrated = helper.runMigrationsAndValidate(TEST_DB, 4, true, MIGRATION_3_4)
    migrated.query("SELECT amount_cents FROM cart WHERE id = 1").use { c ->
        c.moveToFirst(); assertEquals(4500, c.getInt(0))
    }
}
```

### DataStore — Preferences
```kotlin
private val Context.settingsDataStore by preferencesDataStore(name = "settings")

class SettingsRepository(private val context: Context) {
    private object Keys {
        val THEME = stringPreferencesKey("theme")
        val LAST_SYNC = longPreferencesKey("last_sync_ms")
    }

    val theme: Flow<String> = context.settingsDataStore.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { it[Keys.THEME] ?: "system" }

    suspend fun setTheme(value: String) {
        context.settingsDataStore.edit { it[Keys.THEME] = value }
    }
}
```

### DataStore — Proto
```kotlin
val Context.userPrefsDataStore: DataStore<UserPrefs> by dataStore(
    fileName = "user_prefs.pb",
    serializer = UserPrefsSerializer,
)

object UserPrefsSerializer : Serializer<UserPrefs> {
    override val defaultValue: UserPrefs = UserPrefs.getDefaultInstance()
    override suspend fun readFrom(input: InputStream): UserPrefs =
        try { UserPrefs.parseFrom(input) } catch (e: InvalidProtocolBufferException) { throw CorruptionException("corrupt", e) }
    override suspend fun writeTo(t: UserPrefs, output: OutputStream) = t.writeTo(output)
}
```

## Gotchas

### `Worker`(blocking)를 신규 코드에서 사용
취소 전파 누락 + thread 점유. **`CoroutineWorker` 사용.**

### Constraints 안 걸고 enqueue
OS가 임의 시점에 실행 → 사용자 데이터 요금 / 배터리. 항상 명시.

### `OneTimeWorkRequest`를 같은 키로 여러 번 enqueue (`enqueue` vs `enqueueUniqueWork`)
중복 실행 → 데이터 손상 / API rate limit. 항상 `enqueueUniqueWork` + 정책 명시.

### expedited Work에 fallback policy 누락
quota 초과 시 throw. `RUN_AS_NON_EXPEDITED_WORK_REQUEST` 명시.

### Foreground Work에 `foregroundServiceType` Manifest 누락 (Android 14+)
launch 실패 + crash. service type 정확히 매칭.

### `inputData`에 큰 byte array 직접 전달
10KB 초과 시 throw. file path / DB id로 reference만.

### `Result.retry()` 무한 루프
`runAttemptCount` 한도 + `setBackoffCriteria` 명시.

### Room `exportSchema = false`
schema diff 리뷰 불가 + AutoMigration 불가. 항상 `true` + `app/schemas/` git commit.

### `fallbackToDestructiveMigration()` production
사용자 데이터 wipe. 절대 금지. 명시 Migration 또는 AutoMigration.

### Migration test 없이 DB version bump
production OTA에서 crash. `MigrationTestHelper` 필수.

### DAO에서 `LIMIT` 없는 `SELECT *`
큰 테이블에서 OOM 또는 ANR. 페이징 (`Pager`/`PagingSource`) 또는 LIMIT.

### `@Query`에 외부 string interpolation
SQL injection. bind parameter (`:foo`) 사용. `@RawQuery` 사용 시 SimpleSQLiteQuery로 bind.

### `@Transaction` 누락한 multi-statement DAO
부분 실패 시 inconsistent. transaction 명시.

### DataStore 인스턴스를 `Activity`/`ViewModel`에서 생성
같은 name 두 번째 생성 시 throw. **top-level extension property로 단일 인스턴스.**

### DataStore에서 SharedPreferences 마이그레이션 누락
사용자 설정값 사라져 버림. `SharedPreferencesMigration(context, "old_prefs")` 등록.

### DataStore를 list/관계 데이터 저장소로 사용
조회/정렬 안 됨, 큰 데이터 read 비용. **Room이 적합.**

### `collect`로 read 후 즉시 쓰는 1회성 코드
`first()` 사용. collect는 평생 구독.

### Room DAO의 Flow를 `collectAsState` 직접 사용
lifecycle 무시. `collectAsStateWithLifecycle` 또는 `repeatOnLifecycle`.

## 검증 체크리스트

- WorkManager 적합성 (deferrable + 보장) 결정문 존재
- 모든 WorkRequest에 Constraints
- enqueueUniqueWork + ExistingWorkPolicy 적합
- CoroutineWorker 사용
- Expedited Work에 OutOfQuotaPolicy.fallback 명시
- Foreground Work의 foregroundServiceType Manifest 일치
- inputData 크기 10KB 이하
- Room exportSchema = true + schemas/ git commit
- AutoMigration 또는 명시 Migration + MigrationTestHelper test
- fallbackToDestructiveMigration 사용 안 함
- 모든 DAO 쿼리에 LIMIT 또는 페이징
- @Transaction이 multi-statement에 명시
- DataStore가 top-level singleton
- DataStore가 Flow 기반 read + edit 기반 write
- SharedPreferences 신규 도입 없음

## 5축 자가 평가

- 검색성: workmanager / room / datastore / coroutineworker / migration / 한·영 키워드
- 의사결정 트리(IF/THEN): 8개 IF + 13개 리뷰 체크
- 코드 식별자: CoroutineWorker, OneTimeWorkRequestBuilder, Constraints, ExistingWorkPolicy, OutOfQuotaPolicy, ForegroundInfo, @Database, @AutoMigration, MigrationTestHelper, preferencesDataStore, dataStore, edit { }, SharedPreferencesMigration
- Gotcha-driven: 18개 흔한 실수 + 회피
- 검증 가능: 15개 체크리스트

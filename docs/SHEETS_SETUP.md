# Google Sheets 양방향 연결

이 버전은 Apps Script 웹앱을 통해 원장을 읽고 저장한다. Cloud 콘솔·서비스계정·Sheets API 키는 만들지 않는다. 다만 [Apps Script는 Google 관리형 Cloud 프로젝트에 의존](https://developers.google.com/apps-script/guides/cloud-platform-projects)하므로 간접 Cloud 의존까지 없는 방식은 아니다. 사용자 추가 요청에 따라 이 방식으로 변경했다.

## 1. Apps Script 준비

1. 사용할 Google Sheets를 열고 **확장 프로그램 → Apps Script**로 이동한다.
2. 저장소의 [Code.gs](../apps_script/Code.gs)를 스크립트 편집기에 붙여넣고 저장한다. 이전 노션의 단순 appendRow 예제 대신 이 파일을 사용한다.
3. Apps Script **프로젝트 설정 → 스크립트 속성**에 다음 값을 등록한다.
   - `SPREADSHEET_ID`: 시트 URL의 `/d/`와 `/edit` 사이 값.
   - `SHEETS_SECRET`: 직접 생성한 24자 이상 임의 문자열. 코드에 넣거나 채팅으로 보내지 않는다.
4. **배포 → 새 배포 → 웹 앱**을 선택한다. 실행 사용자는 본인, 액세스 대상은 서버에서 접근할 수 있는 **모든 사용자**로 설정하고 배포를 승인한다. 조직 정책이 익명 웹앱을 막으면 이 경로를 사용할 수 없으며 수동 입력·내보내기를 사용한다.
5. 발급된 `https://script.google.com/macros/s/.../exec` URL을 복사한다. `/dev` URL은 사용하지 않는다. URL에 접속하면 데이터 없는 상태 확인 응답만 표시된다.

시트 자체를 링크 공개로 공유할 필요는 없다. 읽기·쓰기 모두 POST 본문 시크릿 인증을 사용하며 URL 파라미터에는 시크릿을 넣지 않는다. Apps Script의 권한을 승인하고 웹앱을 배포하는 단계는 시트 소유자가 수행해야 한다.

## 2. Streamlit 설정

Community Cloud 앱 설정의 **Secrets**에 아래 키를 입력한다. 로컬 실행은 `.streamlit/secrets.toml`에 같은 값을 넣는다. 이 파일은 Git에서 제외된다.

```toml
SHEETS_WEBAPP_URL = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec"
SHEETS_SECRET = "REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_24_CHARACTERS"
APP_PASSWORD = "REPLACE_WITH_A_DIFFERENT_PASSWORD_AT_LEAST_12_CHARACTERS"
```

앱 비밀번호는 공유 Streamlit 서버에서 다른 방문자가 개인 원장을 읽는 것을 막는다. SHEETS_SECRET과 서로 다른 값을 사용한다. 비밀번호를 확인하기 전에는 원장을 읽지 않는다.

Streamlit의 Main file path는 `streamlit_app.py`, Python은 3.12로 설정한다. 개발 브랜치 검토 중에는 해당 브랜치를 별도 앱으로 배포할 수 있다. 기존 main 앱에 반영하려면 PR 병합 후 재배포한다.

## 3. 첫 불러오기와 저장

- 인증 후 세션 시작 시 원장을 한 번 읽는다. 페이지 이동·위젯 조작마다 다시 읽지 않는다.
- 새 문서는 DEMO 0주 예시로 시작한다. 본인 보유내역을 확인·적용한 뒤 저장한다. DEMO 상태에서는 연결 시트에 저장할 수 없다.
- 기존 문서는 기본 6개 탭의 헤더를 유지한다. 없는 확장 탭은 첫 저장 때 생성한다.
- **Sheets에 저장**은 8개 원장을 함께 보존한다. 실제 체결은 Actions의 고유 체결 행으로 남고 Holdings는 최신 잔고로 갱신된다.
- 서버 응답 뒤 모든 표를 다시 읽어 비교한 경우에만 저장 완료를 표시한다. 확인되지 않으면 세션 자료를 유지한다.
- 기록 화면에서 확정 주문안을 다시 열어 다음 날 체결을 이어서 입력할 수 있다.

| 탭 | 저장 내용 |
|---|---|
| Holdings | 실제 수량·CASH·분류·역할·목표 |
| Strategies | 현재 규칙·버전·허용 괴리·소수점·유보액 |
| Snapshots | 평가 원본·개정·고유 ID·관측일 |
| Actions | 실제 체결·부분 체결·취소 |
| Cashflows | 외부 입출금·계좌 간 이체 |
| CategoryTargets | 전체 자산군 목표 |
| Evaluations | 당시 입력·가격 시계열·규칙·주문안의 JSON 조각 |
| StrategyVersions | 변경 전 전략 정의 |

앱은 위 8개 탭의 헤더와 내용을 관리한다. 별도 수식·분석·메모는 다른 탭에 둔다. 종목코드는 문자열로 저장해 `069500` 같은 앞자리 0을 보존한다. 워크북의 다른 이름의 탭은 변경하지 않는다.

## 4. 충돌·재시도·복구

- **응답 시간 초과:** 같은 세션 자료로 저장을 다시 누른다. 동일 요청 ID이면 행을 다시 추가하지 않는다. 백업을 내려받은 뒤 필요하면 설정에서 최신 원장 미리보기를 연다.
- **다른 세션/직접 시트 편집:** 자료 지문이 달라지면 저장을 거절한다. 현재 작업을 JSON으로 백업하고 최신 원장을 미리 본 뒤 필요한 변경을 다시 적용한다. 자동 덮어쓰기·강제 저장은 없다.
- **여러 탭 저장 중 실패:** 서버는 직전 원장을 `_RebalanceRecovery`에 준비한 뒤 쓰기를 시작한다. `_RebalanceState`의 미완료 표지가 남으면 다음 인증 요청에서 직전 원장을 복구한다. 두 관리 탭은 삭제·편집하지 않는다.
- **복구 실패:** 앱은 읽기와 저장을 차단한다. 시트를 복제해 보존한 뒤 관리 탭의 복구 JSON 또는 마지막 전체 백업을 확인한다. 관리 표지를 임의로 지워 부분 저장본을 정상으로 취급하지 않는다.

### `이전 저장 복구에 실패했습니다`가 나타나면

1. 앱에서 **Sheets에 저장**을 다시 누르지 않는다. 원본 스프레드시트에서 **파일 → 사본 만들기**로 현재 상태 전체를 보존한다. 원본이나 `_RebalanceState`, `_RebalanceRecovery`의 내용을 편집하거나 삭제하지 않는다.
2. 같은 시트의 **확장 프로그램 → Apps Script**에서 저장소의 `Code.gs`에 있는 `diagnoseRecovery` 함수를 추가한다. 기존 스크립트에 이미 있으면 다시 추가하지 않는다. 편집기에서 이 함수를 선택해 **실행**하고 실행 로그의 한 줄짜리 JSON을 확인한다. 이 진단은 시트에 쓰지 않으며 비밀값과 셀 내용도 출력하지 않는다. 웹앱 재배포는 진단 실행에 필요하지 않다.
3. 결과의 `state`, `recovery`, `current`, `current_matches_backup`을 확인한다. `state:pending`이면 미완료 표지가 남아 있다. `recovery:valid`이면 이전 원장 백업을 해석할 수 있다. `current_matches_backup:true`이면 현재 8개 원장이 백업과 일치하지만 상태 표지를 정리하지 못한 상태일 수 있다. `false`이면 현재 원장이 백업과 다르므로 부분 저장 여부를 확인해야 한다.
4. `recovery:missing_or_empty`, `invalid_json`, `invalid_workspace`이면 현재 복구 탭만으로 되돌릴 수 없다. **파일 → 버전 기록 → 버전 기록 보기**에서 마지막 정상 저장 시점의 8개 탭과 관리 탭을 살펴보고, 별도의 사본으로 보존한다. 마지막 전체 JSON 백업이 있다면 함께 보존한다. 원본에 과거 버전을 곧바로 복원하면 그 이후 변경을 잃을 수 있다.
5. 진단 JSON을 바탕으로 복구 방법을 결정한다. 시크릿, 원장 행, 복구 JSON 전체를 공유할 필요는 없다. 진단 로그만 공유해도 다음 단계를 좁힐 수 있다. 검증 전에는 `_RebalanceState`의 `pending`을 지우지 않는다.

ScriptLock은 스크립트끼리의 동시 접근만 제어한다. 저장 중 시트를 직접 편집하지 않는다. Google Sheets는 트랜잭션 DB가 아니며 소유자의 동시 직접 편집·권한 변경·쿼터 초과까지 원자적으로 보장하지 않는다. 저장 요청은 5MB 이하로 제한한다.

시트가 원본이어도 삭제·손상과 미저장 작업 손실 가능성은 남는다. 기존 노션의 “별도 백업 불필요” 문구 대신 전체 JSON 백업을 계속 제공한다. 저장 전 편집 중인 평가·체결 입력도 백업 가능하며, 아직 제출하지 않은 폼 입력은 먼저 적용해야 한다.

## 5. 실제 환경에서 확인할 항목

별도 시험용 시트로 시작해 보유내역 저장 → 새 브라우저 세션 불러오기 → 평가 확정 → 실제 체결 입력 → 재접속 후 잔고 확인을 수행한다. 앱의 저장 실패·충돌 메시지도 확인한다. 코드의 모의 저장 테스트는 Google 권한·배포·쿼터·실제 시트 셀 형식 검증을 대신하지 않는다.

참고: [Apps Script 웹앱](https://developers.google.com/apps-script/guides/web), [LockService](https://developers.google.com/apps-script/reference/lock/lock-service).


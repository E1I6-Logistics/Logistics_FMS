# 물류 창고 시스템 FMS 대시보드

물류센터의 로봇, 경로, 작업 및 알람 상태를 화면에서 확인하는 React/Vite 기반 데모 대시보드입니다. 실제 FMS·ROS·MQTT 서버에는 연결하지 않습니다.

## 가장 빠른 실행 방법 (Windows)

처음 사용하는 경우에도 아래 순서만 따르면 됩니다.

1. Windows용 [Node.js LTS](https://nodejs.org/)를 설치합니다. 설치 화면에서는 기본 설정을 그대로 사용합니다.
2. 설치가 끝나면 PowerShell을 새로 열고 아래 명령을 실행합니다.

```powershell
node --version
npm --version
```

두 명령 모두 버전 번호를 보여야 합니다. Node.js는 **22.12 이상**이 필요합니다.

3. pnpm을 한 번만 설치합니다.

```powershell
npm install --global pnpm
pnpm --version
```

4. 파일 탐색기에서 아래 폴더를 엽니다.

```text
S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend
```

5. `start-dashboard.cmd`를 더블클릭합니다.

처음 실행할 때는 의존성을 설치하므로 인터넷 연결이 필요합니다. 완료되면 기본 브라우저가 자동으로 열리고 대시보드가 표시됩니다. 열리지 않을 경우 브라우저 주소창에 `http://127.0.0.1:5173`을 입력합니다.

실행 중인 검은 창은 서버입니다. 대시보드를 사용하는 동안 닫지 마세요. 종료할 때는 해당 창에서 `Ctrl+C`를 누르거나 창을 닫습니다.

## 꼭 지켜야 할 점

이 프로젝트는 **Windows에서 실행**합니다. `start-dashboard.cmd`를 실행할 때는 Windows용 Node.js와 pnpm이 필요합니다.

WSL에서 `npm install` 또는 `pnpm install`을 실행하지 마세요. WSL은 Linux용 네이티브 파일을 만들고, Windows에서 실행할 때 빈 화면 또는 Vite 실행 오류가 발생할 수 있습니다. 이미 WSL로 설치했다면 아래의 “문제 해결” 절차로 복구하세요.

## PowerShell에서 실행하기

더블클릭 대신 PowerShell에서 실행하려면 다음을 사용합니다.

```powershell
cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'
pnpm install --frozen-lockfile
pnpm dev
```

브라우저에서 `http://127.0.0.1:5173`을 엽니다. 의존성 설치가 끝난 다음부터는 `pnpm dev`만 실행하면 됩니다.

## 문제 해결

### `Node.js is required` 또는 `node`를 찾을 수 없음

Windows용 Node.js가 설치되지 않았거나, 설치 직후 열어 둔 PowerShell/파일 탐색기를 계속 사용 중인 경우입니다. Node.js LTS를 설치한 뒤 PowerShell과 파일 탐색기 창을 모두 닫고 새로 엽니다. 그래도 해결되지 않으면 Windows를 재시작합니다.

### `pnpm`을 찾을 수 없음

새 PowerShell에서 아래 명령을 실행합니다.

```powershell
npm install --global pnpm
```

설치가 끝난 뒤 `pnpm --version`으로 확인하고 `start-dashboard.cmd`를 다시 실행합니다.

### 브라우저가 하얗게 보이거나 Vite/rolldown 오류가 남

WSL과 Windows에서 같은 `node_modules`를 사용했을 때 발생할 수 있습니다. 먼저 실행 중인 대시보드 창을 종료하고, **Windows PowerShell**에서 아래 명령을 순서대로 실행합니다.

```powershell
cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'
Remove-Item -LiteralPath .\node_modules -Recurse -Force
pnpm install --frozen-lockfile
pnpm run build
```

마지막 명령에서 `built in ...`이 표시되면 복구된 것입니다. 이후 `start-dashboard.cmd`를 다시 더블클릭합니다.

### `Port 5173 is already in use`

이미 대시보드가 실행 중입니다. 기존 대시보드의 검은 창에서 `Ctrl+C`를 눌러 종료한 뒤 다시 실행합니다. 기존 창을 찾기 어렵다면 PC를 재시작한 후 다시 실행합니다.

## 개발·검증 명령

```powershell
pnpm dev        # 개발 서버 실행
pnpm run build  # 배포용 파일 생성 및 빌드 확인
pnpm typecheck  # TypeScript 검사
pnpm preview    # 빌드 결과 미리보기: http://127.0.0.1:4173
```

배포용 결과물은 `dist` 폴더에 생성됩니다.
## 지도 수정 내용

- 원본 135 × 135 좌표에서 외곽 경계, 작은 구조물 6개, 좌측 하단 두 꺾임, 우측 지그재그 선을 SVG로 재구성했습니다.
- 좌표는 이미지 픽셀 단위입니다. 물리적 거리나 로봇 좌표계 변환은 포함하지 않습니다.
- HTML 목업의 밝은 회색 배경, 옅은 구조물, 노드·경로 색상, 원형 로봇 마커를 적용했습니다.
- 시설 크기와 이름표를 분리했습니다. 구조물 이름 토글은 이름만 숨기며 실제 벽과 구조물은 유지됩니다.
- 지도 드래그 이동, 휠/버튼 확대·축소, 전체 보기, 원본 비교를 지원합니다.
- 원본 비교는 오버레이를 숨기고 동일한 좌표·배율에서 실제 PNG를 표시합니다.
- 로봇 선택 시 상세 패널과 선택 경로가 연동됩니다.
- 경로 토글과 노드·엣지 토글이 각각 독립적으로 동작합니다.
- 작업 분석의 실제 지도에도 동일한 SVG 구조를 사용합니다. 별도의 추상 토폴로지 도식은 원래 구현을 유지합니다.

## 파일 위치

- src/WarehouseGeometry.tsx: 실제 공간 윤곽과 구조물 좌표. 원본을 시각적으로 트레이싱한 UI용 벡터입니다.
- src/WarehouseMap.tsx: 지도 렌더링, 레이어, 데모 경로, 로봇, 이동·확대·원본 비교.
- src/warehouse-map.css: 지도 도구와 범례 스타일.
- src/App.tsx: 전체 관제 대시보드와 지도 연결.
- src/imports/map.png: 사용자 원본 지도.
- vite.config.ts: Figma 전용 설정을 제거한 로컬 실행 설정.

## 데이터 범위

이 결과물은 화면 확인용 데모입니다. 
실제 FMS/ROS/MQTT 서버에 연결하지 않습니다.
로봇 위치, 운행 경로, 작업·알람, 원격 제어 반응은 원본 ZIP의 예시 데이터/시뮬레이션입니다.
실제 운영에 연결하려면 지도 해상도(m/pixel), 원점·방향, 검증된 노드/경로와 서버 API가 필요합니다.

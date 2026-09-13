# 물류 창고 시스템 FMS 대시보드

실제 물류센터 지도를 기반으로 로봇, 경로, 작업 및 알람 상태를 확인하는 React/Vite 대시보드입니다.

## 처음 실행하기

### 1. Node.js 설치

1. [Node.js 공식 사이트](https://nodejs.org/)에서 LTS 버전을 내려받아 설치합니다.
2. 이 프로젝트는 Node.js 22.12 이상이 필요합니다.
3. 설치가 끝나면 열려 있던 터미널을 닫고 새 PowerShell을 엽니다.
4. 다음 명령으로 설치 여부를 확인합니다.

```powershell
node --version
npm --version
```

두 명령 모두 버전이 출력되어야 합니다. `node`를 찾을 수 없다는 메시지가 나오면 Node.js를 다시 설치한 후 Windows를 재시작합니다.

### 2. pnpm 설치

Node.js 설치 프로그램에 포함된 npm으로 pnpm을 설치합니다.

```powershell
npm install --global pnpm
pnpm --version
```

`pnpm --version`에서 버전이 출력되면 준비가 끝났습니다.

### 3. Windows에서 실행

1. 파일 탐색기에서 이 `frontend` 폴더를 엽니다.
2. `start-dashboard.cmd`를 더블클릭합니다.
3. 최초 실행에서는 필요한 패키지를 자동으로 설치하므로 인터넷 연결이 필요합니다.
4. 터미널에 서버 주소가 표시되면 브라우저에서 [http://127.0.0.1:5173](http://127.0.0.1:5173)을 엽니다.
5. 서버를 종료하려면 실행 중인 터미널에서 `Ctrl+C`를 누릅니다.

소스의 `index.html`은 TypeScript와 React 변환이 필요하므로 파일을 직접 열 수 없습니다. `start-dashboard.cmd` 또는 `pnpm dev`로 Vite 개발 서버를 실행해야 합니다.

## 터미널에서 실행

저장소를 다른 위치에 받은 경우 아래 `cd` 경로를 실제 `frontend` 폴더 경로로 변경합니다.

```powershell
cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'
pnpm install --frozen-lockfile
pnpm dev
```

브라우저에서 http://127.0.0.1:5173 접속.
의존성을 설치한 이후에는 `pnpm dev`만 실행합니다.

`Port 5173 is already in use` 오류가 나오면 기존에 실행 중인 개발 서버를 종료한 후 다시 실행합니다.

```powershell
pnpm typecheck
pnpm build
pnpm preview
```

빌드 출력은 dist 폴더이며 preview 주소는 http://127.0.0.1:4173 입니다.

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

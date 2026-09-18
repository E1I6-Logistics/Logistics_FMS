# 물류 창고 시스템 FMS 대시보드

물류센터의 **로봇, 경로, 작업 및 알람 상태**를 화면에서 확인하는  
**React / Vite 기반 FMS 데모 대시보드**입니다.

> 현재 버전은 화면 및 기능 확인을 위한 데모입니다.  
> 실제 FMS / ROS / MQTT 서버에는 연결하지 않습니다.

---

## 1. 실행 환경

지원 환경:

- Windows
- Linux

필수 프로그램:

- Node.js **22.12 이상**
- pnpm

설치 확인:

```bash
node --version
npm --version
pnpm --version
```

`node`, `npm`, `pnpm` 모두 버전 번호가 출력되어야 합니다.

---

# 2. Windows 실행 방법

## 2-1. 처음 실행하는 경우

### ① Node.js 설치

Windows용 Node.js LTS를 설치합니다.

- https://nodejs.org/

설치 화면에서는 기본 설정을 그대로 사용하면 됩니다.

설치 완료 후 **PowerShell을 새로 열고** 다음 명령을 실행합니다.

```powershell
node --version
npm --version
```

Node.js는 **22.12 이상**이어야 합니다.

### ② pnpm 설치

PowerShell에서 다음 명령을 실행합니다.

```powershell
npm install --global pnpm
pnpm --version
```

pnpm 버전이 출력되면 설치가 완료된 것입니다.

### ③ 프로젝트 폴더 이동

파일 탐색기에서 다음 폴더를 엽니다.

```text
S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend
```

### ④ 대시보드 실행

프로젝트 폴더의 다음 파일을 더블클릭합니다.

```text
start-dashboard.cmd
```

처음 실행하는 경우 필요한 의존성을 설치하므로 **인터넷 연결이 필요합니다.**

실행이 완료되면 기본 브라우저가 자동으로 열립니다.

자동으로 열리지 않을 경우 다음 주소에 접속합니다.

```text
http://127.0.0.1:5173
```

실행 중 나타나는 검은 CMD/PowerShell 창은 **개발 서버**입니다.

대시보드를 사용하는 동안 닫지 마세요.

종료하려면 해당 창에서 다음 키를 누릅니다.

```text
Ctrl + C
```

---

## 2-2. Windows PowerShell에서 직접 실행

`start-dashboard.cmd`를 사용하지 않고 직접 실행하려면 다음 명령을 사용합니다.

```powershell
cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'

pnpm install --frozen-lockfile
pnpm dev
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:5173
```

최초 의존성 설치가 끝난 이후에는 일반적으로 다음 명령만 실행하면 됩니다.

```powershell
pnpm dev
```

---

# 3. Linux 실행 방법

## 3-1. Node.js 설치 확인

터미널에서 다음 명령을 실행합니다.

```bash
node --version
npm --version
```

Node.js **22.12 이상**이 필요합니다.

Node.js가 설치되어 있지 않은 경우 사용하는 Linux 배포판에 맞는 방법으로 Node.js LTS를 설치합니다.

설치 후 다시 확인합니다.

```bash
node --version
npm --version
```

---

## 3-2. pnpm 설치

```bash
npm install --global pnpm
pnpm --version
```

pnpm 버전이 출력되면 정상적으로 설치된 것입니다.

---

## 3-3. 프로젝트 폴더 이동

Linux에서 프로젝트가 위치한 경로로 이동합니다.

예시:

```bash
cd ~/Logistics_FMS/frontend
```

실제 프로젝트 위치에 따라 경로를 변경합니다.

---

## 3-4. 의존성 설치

최초 실행 시 다음 명령을 실행합니다.

```bash
pnpm install --frozen-lockfile
```

---

## 3-5. 개발 서버 실행

```bash
pnpm dev
```

브라우저에서 다음 주소에 접속합니다.

```text
http://127.0.0.1:5173
```

종료하려면 실행 중인 터미널에서 다음 키를 누릅니다.

```text
Ctrl + C
```

최초 설치 이후에는 일반적으로 다음 명령만 실행하면 됩니다.

```bash
pnpm dev
```

---

# 4. Windows / Linux 사용 시 주의사항

## Windows와 Linux에서 동일한 `node_modules`를 공유하지 않는 것을 권장합니다.

일부 npm 패키지는 운영체제별 네이티브 바이너리를 사용합니다.

따라서 Windows에서 생성한 `node_modules`를 Linux에서 그대로 사용하거나, Linux에서 생성한 `node_modules`를 Windows에서 그대로 사용하는 경우 다음 문제가 발생할 수 있습니다.

- Vite 실행 오류
- rolldown 관련 오류
- 네이티브 모듈 로딩 실패
- 브라우저 빈 화면
- 빌드 실패

특히 **WSL과 Windows에서 같은 프로젝트 폴더를 사용할 경우 주의해야 합니다.**

운영체제를 변경해서 실행하는 경우 기존 `node_modules`를 삭제한 후 현재 운영체제에서 다시 설치하는 것을 권장합니다.

---

# 5. 문제 해결

## 5-1. Windows

### `Node.js is required` 또는 `node`를 찾을 수 없음

Windows용 Node.js가 설치되지 않았거나 설치 직후 기존 PowerShell 또는 파일 탐색기 창을 계속 사용하고 있을 가능성이 있습니다.

Node.js LTS 설치 후:

1. PowerShell 종료
2. 파일 탐색기 종료
3. 다시 실행

이후 다음 명령으로 확인합니다.

```powershell
node --version
npm --version
```

그래도 해결되지 않으면 Windows를 재시작합니다.

---

### `pnpm`을 찾을 수 없음

새 PowerShell에서 다음 명령을 실행합니다.

```powershell
npm install --global pnpm
```

설치 확인:

```powershell
pnpm --version
```

이후 `start-dashboard.cmd`를 다시 실행합니다.

---

### 브라우저가 하얗게 표시되거나 Vite / rolldown 오류 발생

Windows와 WSL/Linux에서 같은 `node_modules`를 사용했을 때 발생할 수 있습니다.

실행 중인 개발 서버를 종료한 다음 **Windows PowerShell**에서 다음 명령을 실행합니다.

```powershell
cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'

Remove-Item -LiteralPath .\node_modules -Recurse -Force

pnpm install --frozen-lockfile

pnpm run build
```

마지막 명령에서 다음과 비슷한 메시지가 출력되면 정상적으로 복구된 것입니다.

```text
built in ...
```

이후 다시 실행합니다.

```powershell
pnpm dev
```

또는 `start-dashboard.cmd`를 더블클릭합니다.

---

## 5-2. Linux

### `node: command not found`

Node.js가 설치되지 않았거나 PATH가 적용되지 않은 상태입니다.

설치 후 다음 명령으로 확인합니다.

```bash
node --version
npm --version
```

Node.js **22.12 이상**인지 확인합니다.

---

### `pnpm: command not found`

다음 명령을 실행합니다.

```bash
npm install --global pnpm
```

설치 확인:

```bash
pnpm --version
```

---

### Windows에서 사용한 프로젝트를 Linux에서 실행했더니 오류 발생

기존 `node_modules`를 삭제하고 Linux 환경에서 다시 설치합니다.

```bash
rm -rf node_modules

pnpm install --frozen-lockfile

pnpm run build
```

빌드가 정상적으로 완료되면 다음 명령을 실행합니다.

```bash
pnpm dev
```

---

# 6. `Port 5173 is already in use`

다음과 같은 메시지가 표시되는 경우:

```text
Port 5173 is already in use
```

이미 개발 서버가 실행 중일 가능성이 높습니다.

기존 서버가 실행 중인 터미널에서 다음 키를 눌러 종료합니다.

```text
Ctrl + C
```

이후 다시 실행합니다.

Vite가 자동으로 다른 포트를 선택했다면 터미널에 표시된 주소로 접속합니다.

예시:

```text
http://127.0.0.1:5174
```

---

# 7. 개발 및 검증 명령

Windows와 Linux 모두 동일하게 사용할 수 있습니다.

## 개발 서버 실행

```bash
pnpm dev
```

기본 주소:

```text
http://127.0.0.1:5173
```

## 배포용 빌드

```bash
pnpm run build
```

배포용 파일을 생성하고 정상적으로 빌드되는지 확인합니다.

배포 결과물은 다음 폴더에 생성됩니다.

```text
dist/
```

## TypeScript 검사

```bash
pnpm typecheck
```

## 빌드 결과 미리보기

```bash
pnpm preview
```

기본 주소:

```text
http://127.0.0.1:4173
```

---

# 8. 주요 파일 위치

## `src/WarehouseGeometry.tsx`

실제 공간의 외곽 윤곽과 구조물 좌표를 관리합니다.

원본 지도를 시각적으로 트레이싱하여 만든 **UI용 벡터 데이터**입니다.

## `src/WarehouseMap.tsx`

다음 지도 관련 기능을 담당합니다.

- 지도 렌더링
- 지도 레이어
- 데모 경로
- 로봇 표시
- 지도 이동
- 확대 / 축소
- 원본 지도 비교

## `src/warehouse-map.css`

지도 관련 UI 스타일을 관리합니다.

주요 대상:

- 지도 도구
- 컨트롤 버튼
- 범례
- 지도 표시 스타일

## `src/App.tsx`

전체 FMS 관제 대시보드와 지도를 연결하는 메인 애플리케이션입니다.

## `src/imports/map.png`

사용자가 제공한 원본 물류 창고 지도 이미지입니다.

## `vite.config.ts`

Vite 실행 설정입니다.

기존 Figma 전용 설정을 제거하고 로컬 개발 환경에 맞게 구성되어 있습니다.

---

# 9. 실행 방법 요약

## Windows

최초 1회:

```powershell
npm install --global pnpm

cd 'S:\Sangong\E1i6_Logistics\Logistics_FMS\frontend'

pnpm install --frozen-lockfile
```

실행:

```powershell
pnpm dev
```

또는:

```text
start-dashboard.cmd
```

접속:

```text
http://127.0.0.1:5173
```

---

## Linux

최초 1회:

```bash
npm install --global pnpm

cd ~/Logistics_FMS/frontend

pnpm install --frozen-lockfile
```

실행:

```bash
pnpm dev
```

접속:

```text
http://127.0.0.1:5173
```

---

# 10. 핵심 주의사항

> **Windows와 Linux / WSL에서 동일한 `node_modules`를 공유하지 않는 것을 권장합니다.**

운영체제를 변경하여 실행해야 할 경우 다음 순서로 다시 설치합니다.

```text
node_modules 삭제
→ pnpm install --frozen-lockfile
→ pnpm run build
→ pnpm dev
```

이 과정을 통해 대부분의 운영체제 간 의존성 문제를 방지할 수 있습니다.
# GeoJSON + cmd_vel frontend patch

적용 파일:

- `src/App.tsx` 교체
- `src/WarehouseMap.tsx` 교체
- `src/api/fmsApi.ts` 추가
- `src/hooks/useRouteGraph.ts` 추가
- `src/hooks/useCmdVel.ts` 추가

기존 `WarehouseGeometry.tsx`, CSS 등은 그대로 사용.

기본 backend 주소는 `http://127.0.0.1:8000`.
필요하면 Vite 환경변수로 변경:

```env
VITE_FMS_API_BASE=http://127.0.0.1:8000
VITE_FMS_WS_BASE=ws://127.0.0.1:8000
```

## 동작

- `/api/route/nodes` + `/api/route/graph`에서 GeoJSON 기반 노드/엣지 로드
- 특정 노드 이동은 `/api/command/goal-node` 호출
- 선택 로봇 수동제어는 `/ws/cmd_vel`
- 관리자 모드 + 원격제어 ON일 때 키 입력 활성
- W: 전진, S: 후진
- Q/A: 좌회전
- E/D: 우회전
- Space: 정지
- WebSocket 종료/blur 시 0 cmd_vel 전송

현재 로봇의 지도 좌표는 기존 demo marker를 유지. 다음 단계에서 `/api/robots` + `/ws/dashboard` telemetry로 교체 가능.

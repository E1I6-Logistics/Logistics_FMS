// React 라이브러리에서 StrictMode(엄격 모드 검사기)를 불러옵니다.
import { StrictMode } from 'react';
// 브라우저의 실제 DOM 트리에 React의 가상 DOM을 연결(Mount)해주기 위한 React 18+ 전용 메서드를 불러옵니다.
import { createRoot } from 'react-dom/client';
// 위에서 분석한 전역 CSS 파일을 불러와 전체 앱에 스타일을 입힙니다.
import './index.css';
// 개발자가 작성한 최상위 컴포넌트(UI의 메인 껍데기)를 불러옵니다.
import App from './App.jsx';

// 1. document.getElementById('root')를 통해 public/index.html 파일 안에 비어있는 <div id="root"></div> 요소를 찾습니다.
// 2. createRoot()를 사용해 해당 div를 React가 통제할 캔버스(Root DOM)로 만듭니다.
// 3. .render()를 호출하여 그 캔버스 위에 <App /> 컴포넌트(실제 화면 UI)를 그려냅니다(렌더링).
createRoot(document.getElementById('root')).render(
  // <StrictMode>는 개발 환경(dev)에서만 동작하는 React의 디버깅 래퍼입니다.
  // 이 안에 <App />을 넣으면 React가 일부러 컴포넌트를 두 번씩 렌더링하면서 생명주기 오류나 오래된 API 사용 등의 잠재적 버그를 잡아내어 콘솔에 경고를 띄워줍니다. (실제 배포 버전에선 두 번 렌더링되지 않습니다)
  <StrictMode>
    <App />
  </StrictMode>,
);
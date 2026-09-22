# 경로 서비스 테스트

`tests/mock/`에는 실제 지도나 로봇에 의존하지 않는 고정 GeoJSON과 LLM 응답 예시가 있습니다. `tests/test_*_service.py`는 서비스 함수별 동작을 검증합니다. LLM 비교 테스트는 provider 함수를 mock 처리하므로 API 키, Ollama, ROS, Docker가 필요하지 않습니다.

WSL에서 프로젝트 루트를 연 뒤 Python 인터프리터로 `~/venv/robot/bin/python`을 선택하세요. VS Code의 **Testing** 패널에서 새로고침을 누르면 파일·테스트 함수별 ▶ 버튼으로 선택 실행할 수 있습니다. Python 확장이 설치되어 있어야 합니다.

터미널에서는 다음과 같이 실행합니다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest discover -s tests -t . -p 'test_*.py' -v
python -m unittest tests.test_route_comparison_service.RouteComparisonServiceTest.test_missing_directed_edge_is_rejected -v
```

실제 Ollama 모델 결과를 비교하는 실험은 `simulation/run_llm_comparison.py`에서 별도로 실행합니다. 이 테스트 모음은 모델 성능을 평가하지 않습니다.

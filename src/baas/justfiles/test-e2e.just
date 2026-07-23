test-e2e-baseline mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_baseline {{mode}} {{overlay}}

test-e2e-mock-hook mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_mock_failure_hook {{mode}} {{overlay}}

test-e2e-mock-create mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_mock_failure_create {{mode}} {{overlay}}

test-e2e-mock-destroy mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_mock_failure_destroy {{mode}} {{overlay}}

test-e2e-mock-device-not-found mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_mock_failure_device_not_found {{mode}} {{overlay}}

test-e2e-paas-operations mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_paas_operations {{mode}} {{overlay}}

test-e2e-bot-run-lifecycle mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_bot_run_lifecycle {{mode}} {{overlay}}

test-e2e-bot-run-concurrency mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_bot_run_concurrency {{mode}} {{overlay}}

test-e2e-full mode='bare' overlay='e2e-sqlite':
    source scripts/lib/test-stages.sh && run_e2e_tests {{mode}} {{overlay}}

test-testclient:
    source scripts/lib/test-stages.sh && run_testclient_tests

test-testclient-health-check:
    uv run pytest tests/testclient/health_check/ -v --tb=short --color=yes

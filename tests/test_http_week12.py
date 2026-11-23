#!/usr/bin/env python3
"""External HTTP checks against an already-running HazardScope Week 12 FastAPI server.

Does not retrain, modify artifacts or change the repository. Run after starting uvicorn.
"""
import argparse
import sys
import requests

REQUIRED = {
    "event_id", "reference_region", "magnitude", "depth_km", "anomaly_score",
    "reference_score_percentile", "classification", "model_version", "score_direction",
    "threshold", "threshold_method", "interpretation_caution", "observed_or_hypothetical",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8002')
    args = parser.parse_args()
    url = args.base_url.rstrip('/')
    count = 0

    def check(label, method, path, payload=None, status=200):
        nonlocal count
        r = requests.request(method, url + path, json=payload, timeout=15)
        if r.status_code != status:
            raise AssertionError(f'{label}: HTTP {r.status_code}, expected {status}: {r.text[:450]}')
        try:
            data = r.json()
        except ValueError as exc:
            raise AssertionError(f'{label}: non-JSON response') from exc
        count += 1
        print(f'PASS {count}: {label} (HTTP {status})')
        return data

    healthy = check('model health', 'GET', '/health')
    if healthy.get('status') != 'ready':
        raise AssertionError(f'Unexpected health response: {healthy}')
    info = check('model information', 'GET', '/model-info')
    if info.get('model_version') != healthy.get('model_version'):
        raise AssertionError('Model information/version mismatch')
    doc = check('OpenAPI schema', 'GET', '/openapi.json')
    predict_route = doc.get('paths', {}).get('/predict', {}).get('post', {})
    response_200 = predict_route.get('responses', {}).get('200', {})
    if not response_200.get('content', {}).get('application/json', {}).get('schema', {}).get('$ref', '').endswith('/PredictionResponse'):
        raise AssertionError('OpenAPI 200 response does not reference PredictionResponse: apply the patch')

    payload = {"magnitude": 4.7, "depth_km": 15.0, "reference_region": "california_bbox"}
    result = check('valid model prediction', 'POST', '/predict', payload)
    missing = REQUIRED - set(result)
    if missing:
        raise AssertionError(f'Prediction missing keys: {sorted(missing)}')
    if result['classification'] not in ('unusual_in_reference', 'within_reference_range'):
        raise AssertionError(f'Unexpected classification: {result["classification"]!r}')
    if not 0 <= result['reference_score_percentile'] <= 100:
        raise AssertionError('Invalid reference percentile')
    if result['model_version'] != healthy['model_version']:
        raise AssertionError('Prediction model version differs from /health')
    print(f'    Model version: {result["model_version"]}; classification: {result["classification"]}; '
          f'score: {result["anomaly_score"]:.6f}; percentile: {result["reference_score_percentile"]:.2f}')

    check('invalid magnitude rejected', 'POST', '/predict', dict(payload, magnitude='bad'), 422)
    check('unsupported region rejected', 'POST', '/predict', dict(payload, reference_region='alaska'), 422)
    check('missing required field rejected', 'POST', '/predict', {'magnitude': 4.7, 'reference_region': 'california_bbox'}, 422)
    print(f'\nALL {count} HTTP CHECKS PASSED. Capture the /docs success and 422 screenshots separately.')

if __name__ == '__main__':
    try:
        main()
    except (requests.RequestException, AssertionError) as e:
        print(f'FAILED: {e}', file=sys.stderr)
        sys.exit(1)

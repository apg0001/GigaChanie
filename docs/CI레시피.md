# CI 레시피 (헤드리스 GigaChanie)

`giga` 는 헤드리스로 동작하므로 CI 에서 리뷰·수정 잡으로 쓸 수 있다.
아래 예제는 로컬/사내 러너에 Ollama(또는 OpenAI 호환 엔드포인트)가 있다고
가정한다. 공개 GitHub 러너에는 모델이 없으므로 `GIGA_BASE_URL` /
`GIGA_API_KEY` 로 원격 엔드포인트를 가리키는 편이 현실적이다.

## 1. PR 자동 리뷰 (변경 사항만 코멘트)

```yaml
# .github/workflows/giga-review.yml
name: giga review
on: pull_request

jobs:
  review:
    runs-on: [self-hosted]      # Ollama 가 설치된 러너
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: pip install gigachanie
      - name: 모델 준비
        run: giga model use qwen2.5-coder:7b
      - name: 변경 리뷰
        run: |
          giga review --range "origin/${{ github.base_ref }}...HEAD" \
            --task "이 PR 의 회귀 위험과 놓친 엣지 케이스" | tee review.md
      - name: 결과를 PR 코멘트로
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: review.md
```

`giga review` 는 지적사항이 있으면 종료코드 1 을 돌려주므로, 그대로 두면
"리뷰에 코멘트가 있으면 실패"가 된다. 코멘트만 남기고 통과시키려면
`giga review ... || true`.

## 2. 이슈 → 자동 수정 PR

```yaml
# .github/workflows/giga-fix.yml
name: giga fix
on:
  workflow_dispatch:
    inputs:
      task: { description: "고칠 내용", required: true }

jobs:
  fix:
    runs-on: [self-hosted]
    steps:
      - uses: actions/checkout@v4
      - run: pip install gigachanie
      - run: giga model use qwen2.5-coder:7b
      - name: 에이전트 실행 (헤드리스)
        run: |
          giga agent --json -w --mode full-auto --max-steps 30 \
            "${{ inputs.task }}" > result.json
          cat result.json
      - name: 검증
        run: |
          test "$(jq -r .ok result.json)" = "true"
          ruff check . && pytest -q
      - name: PR 생성
        run: giga pr --base main --create
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## 3. eval 회귀 게이트

```yaml
      - name: eval 통과율 게이트
        run: giga eval --json | tee eval.json
        # 전부 통과해야 종료코드 0. 실패 태스크가 있으면 잡이 빨갛게 뜬다.
```

## 참고

- `giga agent --json` 출력: `{ok, final_text, stop_reason, steps, tokens, changed_files}`
- `giga runlog --stats` 로 여러 실행의 통과율·토큰 추이를 본다.
- 원격 엔드포인트: `giga model use <ID> --base-url https://… ` + 환경변수
  `GIGA_API_KEY`.

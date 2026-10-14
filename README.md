# Server

The search API of [www.iloveconference.org](https://www.iloveconference.org). It answers a
question about general conference talks: it embeds the question with OpenAI, finds matching talk
excerpts in a Pinecone index, and has an OpenAI model answer from them.

It's a FastAPI app that runs on AWS Lambda behind the site's CloudFront distribution, which also
serves the static front end (the `client` repo). This repo also holds the CloudFormation templates
for all of it and the GitHub Actions workflows that test and deploy it.

Routes:

- `GET /api/search?q=…` returns JSON with `q`, `session`, `answer` and `results` (each with `id`,
  `title`, `author`, `year`, `month`, `url` and `text`). `q` must be 1–100 characters, or FastAPI
  returns 422.
- `GET /api/warm` returns 204 with no body and does no paid work. Every page but `/search` calls
  it when it loads, so Lambda's cold start is over before the visitor's first search. On top of
  that, an EventBridge schedule (`ilc-search-warm-up`) invokes the function every 5 minutes with
  `{"ilc_warm_up": true}`, which returns at once, so one execution environment normally stays warm.
- `GET /api/health` returns 200 `OK`.

Before any paid call, a search checks two Upstash rate limits: 40 searches per client in any 24
hours, then 300 searches per UTC day for the whole site. A client is an IP address, or an IPv6 /64,
from the `CloudFront-Viewer-Address` header; Upstash only sees a keyed hash of it. Errors are JSON
`{"error": …, "message": …}`:

- 429 `rate_limited`: the client's limit.
- 429 `busy`: the site's daily limit.
- 503 `unavailable`: Upstash failed or took over 2 seconds, so the search was refused (fail closed).
- 400 `bad_request`: in Lambda, the request has no `CloudFront-Viewer-Address` header.

## Local development

You need Python 3.12 and Poetry 2.5.1 with poetry-plugin-export 1.10.1, the versions CI pins in
`.github/workflows/constraints.txt`. With uv, for example:

```console
uv tool install poetry==2.5.1 --with poetry-plugin-export==1.10.1
poetry install
```

Create `.env` in the repo root (it's gitignored):

```console
OPENAI_KEY=...
PINECONE_KEY=...
UPSTASH_REDIS_REST_URL=https://....upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

All four are required: `load_secrets()` runs at import and raises `KeyError` on any
missing name, so the app will not start without them.

Rather than copy the production secrets into a second file on disk, you can pull them
into the shell for one session:

```console
eval "$(aws ssm get-parameters --with-decryption --region us-west-2 \
  --names /ilc/prod/OPENAI_KEY /ilc/prod/PINECONE_KEY \
          /ilc/prod/UPSTASH_REDIS_REST_URL /ilc/prod/UPSTASH_REDIS_REST_TOKEN \
  --query 'Parameters[].[Name,Value]' --output text \
  | sed 's|/ilc/prod/||' | awk '{print "export "$1"=\""$2"\""}')"
```

Note the test suite proves nothing about these: `tests/conftest.py` injects fakes
before `server.main` is imported, so `pytest` is green with an empty `.env`. To check
the real path:

```console
env -u SSM_PREFIX .venv/bin/python -c "from server.config import load_secrets; load_secrets()"
```

`RATE_LIMIT_PER_CLIENT` and `RATE_LIMIT_GLOBAL_DAILY` override the limits. Leave `SSM_PREFIX` and
`METRIC_NAMESPACE` unset: in Lambda they make the app read its secrets from SSM Parameter Store and
print CloudWatch metric lines.

Run the API on port 8000:

```console
poetry run uvicorn server.main:app --reload
```

Without real Upstash credentials every search returns 503. With the production database, local
searches count toward the production limits.

To use it from the site, run the `client` repo's dev server (`pnpm dev`), which proxies `/api/*`
to `http://localhost:8000`.

## Tests

```console
poetry run pytest
poetry run mypy server tests docs/conf.py
```

The route tests send Lambda function URL events through the Mangum handler. OpenAI, Pinecone,
Upstash and SSM are replaced by fakes, so no test makes a network call.

CI runs the checks through nox, with nox 2026.8.17 and nox-poetry 1.2.0
(`uv tool install nox==2026.8.17 --with nox-poetry==1.2.0`):

```console
nox --python=3.12 --sessions pre-commit mypy tests typeguard  # must pass
nox --python=3.12 --sessions safety docs-build                # reported, never blocking
```

## Deploys

Stack `ilc` (`template.yaml`, us-west-2) is the running site. GitHub Actions deploys it:

1. `.github/workflows/tests.yml` runs on every push and pull request. Its `tests` job runs the nox
   sessions that must pass; the `checks` job runs `safety` and `docs-build` and never fails the
   workflow.
2. On a push to `main`, after `tests` passes, its `deploy` job calls the reusable workflow
   `.github/workflows/deploy.yml`. On an arm64 runner, that workflow:
   - exports `requirements.txt` from `poetry.lock` and runs `sam build`, before it has any AWS
     credentials;
   - assumes the `ilc-server-deploy` role through GitHub's OIDC provider (no stored AWS keys);
   - runs `sam deploy`: the package goes to the artifacts bucket, and CloudFormation updates stack
     `ilc` through the `ilc-cfn-exec` service role;
   - checks that `/api/health` returns `OK` and `/api/warm` returns 204 on the CloudFront domain,
     then runs one real search and checks that it returns an answer and results. The search
     costs well under a cent and counts toward the day's limits; if it gets a 429, the job only
     warns. Its query ends in "(deploy smoke test)", so it can be told apart in the log archive.

`deploy.yml` reads five repository variables (Settings > Secrets and variables > Actions >
Variables), set during the bootstrap below. Don't give either job a GitHub environment: that
changes the OIDC token's `sub` claim, and `ilc-server-deploy` only trusts
`repo:iloveconference/server:ref:refs/heads/main`.

The `client` repo's CI uploads the site the same way, with the `ilc-client-deploy` role that stack
`ilc` creates.

`scripts/deploy-manual.sh` deploys stack `ilc` from your machine, with admin credentials, through
`ilc-cfn-exec` as CI does. It builds with `scripts/build.sh`, which runs the pinned Poetry with uvx
and, except on Linux arm64, runs `sam build` in SAM's arm64 build container (Docker). Set
`SAM="uvx --from aws-sam-cli sam"` if the SAM CLI isn't installed. The script always passes the two
search limits, so a test deploy can lower them
(`PER_CLIENT_DAILY_LIMIT=2 GLOBAL_DAILY_LIMIT=3 scripts/deploy-manual.sh`) and a second run without
them restores 40 and 300. CI keeps whatever values the last deploy set.

## Rotating a secret

Updating the SSM parameter is not enough. `load_secrets()` runs at import, so each Lambda
execution environment reads the secrets once and keeps them for its lifetime, and the `WarmUp`
schedule keeps one environment alive indefinitely. After a rotation that environment goes on
presenting the old value: with a revoked `OPENAI_KEY` every search fails on the embedding call
with a 401, which the page shows as "Search is temporarily unavailable."

So rotate in two steps. Write the new value:

```console
aws ssm put-parameter --region us-west-2 --type SecureString --overwrite \
  --name /ilc/prod/OPENAI_KEY --value "..."
```

Then force new execution environments by changing the function's configuration, which `sam deploy`
(or `scripts/deploy-manual.sh`) does as a side effect. Without a deploy to make, any configuration
change will do, as long as it keeps every variable `template.yaml` sets:

```console
vars=SSM_PREFIX=/ilc/prod/,METRIC_NAMESPACE=server_prod,SECRETS_ROTATED=$(date +%F)
aws lambda update-function-configuration --region us-west-2 --function-name ilc-search \
  --environment "Variables={$vars,RATE_LIMIT_PER_CLIENT=40,RATE_LIMIT_GLOBAL_DAILY=300}"
```

`--environment` replaces the whole map rather than merging into it, so read the deployed values
first (`aws lambda get-function-configuration --region us-west-2 --function-name ilc-search`),
since CI keeps whatever search limits the last deploy set. `SECRETS_ROTATED` is there only to
make the call a real change, since re-sending identical values can be a no-op; the next
`sam deploy` drops it.

`/api/warm` doesn't prove a rotation worked, because nothing on that path calls OpenAI. Run a
search instead, and check the log group for a `"message": "search"` entry rather than a 401.

## One-time bootstrap

Run these once, in order, from the repo root, with admin credentials for the AWS account.
`scripts/bootstrap.sh` with no arguments prints every step's command with the stack outputs filled
in.

First:

- Create the four secrets as SecureString parameters in us-west-2: `/ilc/prod/OPENAI_KEY`,
  `/ilc/prod/PINECONE_KEY`, `/ilc/prod/UPSTASH_REDIS_REST_URL` and
  `/ilc/prod/UPSTASH_REDIS_REST_TOKEN`. While Copilot's parameters still exist, this copies them
  without printing the values:

  ```console
  for name in OPENAI_KEY PINECONE_KEY UPSTASH_REDIS_REST_URL UPSTASH_REDIS_REST_TOKEN; do
    aws ssm put-parameter --region us-west-2 --type SecureString --name "/ilc/prod/$name" \
      --value "$(aws ssm get-parameter --region us-west-2 --with-decryption \
        --name "/copilot/ilc/prod/secrets/$name" --query Parameter.Value --output text)"
  done
  ```

- Activate `project` as a cost allocation tag (Billing console > Cost allocation tags), so the
  budget sees the stacks' costs. It takes about a day.
- Install Docker, uv and the SAM CLI.

Then:

1. Stack `ilc-edge` (`edge.yaml`, us-east-1): the certificate, the `ilc-alerts-edge` topic, the
   certificate expiry alarm and the $5 monthly budget (or `scripts/bootstrap.sh --run edge`):

   ```console
   aws cloudformation deploy --region us-east-1 --stack-name ilc-edge --template-file edge.yaml \
     --tags project=ilc --no-fail-on-empty-changeset
   ```

   It finishes once the certificate is issued, which the validation CNAMEs already in the
   `iloveconference.org` zone allow. Alerts and budget emails go to dallan@genefun.com; add
   `--parameter-overrides AlertEmail=<address>` for another address. Confirm the subscription in
   the email from AWS Notifications.

2. Stack `ilc-github` (`github.yaml`, us-west-2): the artifacts bucket, the
   `ilc-permissions-boundary` policy, and the `ilc-cfn-exec` and `ilc-server-deploy` roles (or
   `scripts/bootstrap.sh --run github`):

   ```console
   aws cloudformation deploy --region us-west-2 --stack-name ilc-github --template-file github.yaml \
     --capabilities CAPABILITY_NAMED_IAM --tags project=ilc --no-fail-on-empty-changeset
   ```

3. Stack `ilc`, the first time by hand, from the branch that will be merged:

   ```console
   scripts/deploy-manual.sh
   ```

   If CloudFormation is denied an action, the stack ends in `ROLLBACK_COMPLETE` and its events
   name the action. Add it to `ilc-cfn-exec` in `github.yaml`, run step 2 again, delete the stack,
   and retry:

   ```console
   aws cloudformation delete-stack --region us-west-2 --stack-name ilc
   aws cloudformation wait stack-delete-complete --region us-west-2 --stack-name ilc
   ```

   Then confirm the `ilc-alerts` subscription email, and check that
   `https://<DistributionDomainName>/api/health` returns `OK`.

4. Stack `ilc-edge` again, with stack `ilc`'s `DistributionId` output, which adds the CloudFront
   5xx alarm:

   ```console
   scripts/bootstrap.sh --run edge-alarm
   ```

5. The GitHub Actions variables (not secrets), with `gh` logged in as an admin of both repos:

   ```console
   scripts/bootstrap.sh --run github-vars
   ```

   It sets these from the stack outputs:

   - server: `AWS_SERVER_DEPLOY_ROLE_ARN`, `AWS_CFN_EXEC_ROLE_ARN`, `SAM_ARTIFACTS_BUCKET` and
     `PERMISSIONS_BOUNDARY_ARN` (outputs `ServerDeployRoleArn`, `CfnExecRoleArn`,
     `ArtifactsBucketName` and `PermissionsBoundaryArn` of `ilc-github`), and `CERTIFICATE_ARN`
     (`CertificateArn` of `ilc-edge`);
   - client: `AWS_CLIENT_DEPLOY_ROLE_ARN` (`ClientDeployRoleArn` of `ilc`).

6. Merge this repo's pull request (CI deploys stack `ilc`, normally with no changes), then the
   `client` repo's (CI uploads the site).

DNS isn't part of any stack: the Route 53 alias records for `iloveconference.org` and
`www.iloveconference.org` are pointed at the distribution's `DistributionDomainName` by hand.

## Rollback

Revert the commit on `main` and push: CI deploys the previous version. CloudFormation rolls back a
deploy that fails on its own.

The artifacts bucket keeps packages for 30 days. A deploy that fails more than 30 days after the
last successful one can leave the stack in `UPDATE_ROLLBACK_FAILED`, because the previous package
is gone. Recover with
`aws cloudformation continue-update-rollback --region us-west-2 --stack-name ilc --resources-to-skip SearchFunction`,
then deploy again.

## Architecture

```text
browser ─► CloudFront: www.iloveconference.org (iloveconference.org redirects there)
             ├─ default ─► S3 site bucket: the client repo's static build. A CloudFront Function
             │             redirects /x/ to /x and serves / from /index.html and /x from /x.html.
             └─ /api/*  ─► Lambda function URL (AWS_IAM auth; CloudFront signs requests with OAC)
                           ilc-search: FastAPI + Mangum, Python 3.12, arm64, at most 10 at once
                           ├─ Upstash Redis: the per-client and site-wide daily limits
                           ├─ OpenAI embedding ─► Pinecone query ─► OpenAI answer
                           ├─ JSON log lines (logger "server.main") ─► Firehose server-logs
                           │    ─► s3://iloveconference.logs (read by the models repo)
                           └─ metric lines (Embedded Metric Format) ─► CloudWatch, server_prod
```

Stacks:

- `ilc` (`template.yaml`, us-west-2, deployed by CI): the site bucket, CloudFront, the `ilc-search`
  function, the `ilc-client-deploy` role, and the `ilc-alerts` topic with the Lambda errors and
  throttles alarms.
- `ilc-edge` (`edge.yaml`, us-east-1, by hand): the certificate, and the `ilc-alerts-edge` topic
  with the certificate expiry and CloudFront 5xx alarms and the budget.
- `ilc-github` (`github.yaml`, us-west-2, by hand): the artifacts bucket, the
  `ilc-permissions-boundary` policy, and the `ilc-cfn-exec` and `ilc-server-deploy` roles.

Every role in stack `ilc` carries `ilc-permissions-boundary`, and `ilc-cfn-exec` can only create
roles that do, so a template pushed to `main` can't create a more powerful role.

The code is in `server/`: `main.py` (routes, rate limiting, search), `search_utils.py` (prompt,
client address, metric line), `config.py` (secrets from SSM or `.env`), `lambda_handler.py` (the
Lambda entry point) and `logging.ini`.

## License

Distributed under the terms of the [MIT license][license].

<!-- github-only -->

[license]: https://github.com/iloveconference/server/blob/main/LICENSE

#!/usr/bin/env bash
# Deploy stack "ilc" (template.yaml, us-west-2) by hand: bootstrap step 3, run with admin
# credentials. It deploys through the ilc-cfn-exec service role exactly as CI does, so a
# permission that github.yaml is missing fails here first; add it there, redeploy ilc-github,
# and run this again.
#
# Reads CfnExecRoleArn, ArtifactsBucketName and PermissionsBoundaryArn from stack ilc-github
# (us-west-2) and CertificateArn from stack ilc-edge (us-east-1), builds with scripts/build.sh,
# then runs sam deploy.
#
# Environment:
#   PER_CLIENT_DAILY_LIMIT  searches per client IP per 24 hours (default 40)
#   GLOBAL_DAILY_LIMIT      searches per day in total (default 300)
#   SKIP_BUILD=1            deploy the existing .aws-sam/build instead of building
#   CONFIRM=1               show the change set and ask before executing it
#   SAM, POETRY             commands to run the SAM CLI and Poetry (see scripts/build.sh)
#
# The two limits are always passed. sam deploy keeps a parameter's previous value when it is
# left out (and CI leaves them out), so after a test deploy with low limits, for example
#   PER_CLIENT_DAILY_LIMIT=2 GLOBAL_DAILY_LIMIT=3 scripts/deploy-manual.sh
# run this script again without them to restore 40 and 300.
#
# If the first create fails, the stack is left in ROLLBACK_COMPLETE and has to be deleted
# before the next attempt:
#   aws cloudformation delete-stack --stack-name ilc --region us-west-2
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

read -r -a sam <<<"${SAM:-sam}"

# Prints output KEY of stack STACK in REGION, or exits if the stack or output is missing.
stack_output() {
	local stack="$1" region="$2" key="$3" value
	value="$(aws cloudformation describe-stacks --stack-name "$stack" --region "$region" --output text \
		--query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue | [0]")"
	if [[ -z "$value" || "$value" == None ]]; then
		echo "deploy-manual.sh: stack $stack ($region) has no output $key" >&2
		return 1
	fi
	printf '%s\n' "$value"
}

caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
cfn_exec_role_arn="$(stack_output ilc-github us-west-2 CfnExecRoleArn)"
artifacts_bucket="$(stack_output ilc-github us-west-2 ArtifactsBucketName)"
boundary_arn="$(stack_output ilc-github us-west-2 PermissionsBoundaryArn)"
certificate_arn="$(stack_output ilc-edge us-east-1 CertificateArn)"
per_client_limit="${PER_CLIENT_DAILY_LIMIT:-40}"
global_limit="${GLOBAL_DAILY_LIMIT:-300}"

echo "Deploying stack ilc as $caller_arn"
echo "  service role:     $cfn_exec_role_arn"
echo "  artifacts bucket: $artifacts_bucket"
echo "  certificate:      $certificate_arn"
echo "  boundary:         $boundary_arn"
echo "  limits:           $per_client_limit per client, $global_limit in total per day"

if [[ "${SKIP_BUILD:-}" != 1 ]]; then
	scripts/build.sh
fi

confirm=--no-confirm-changeset
if [[ "${CONFIRM:-}" == 1 ]]; then
	confirm=--confirm-changeset
fi

"${sam[@]}" deploy \
	--stack-name ilc \
	--region us-west-2 \
	--role-arn "$cfn_exec_role_arn" \
	--s3-bucket "$artifacts_bucket" \
	--tags project=ilc \
	--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
	--no-fail-on-empty-changeset \
	"$confirm" \
	--parameter-overrides \
	"CertificateArn=$certificate_arn" \
	"PermissionsBoundaryArn=$boundary_arn" \
	"PerClientDailyLimit=$per_client_limit" \
	"GlobalDailyLimit=$global_limit"

aws cloudformation describe-stacks --stack-name ilc --region us-west-2 --output table \
	--query "Stacks[0].Outputs[].[OutputKey, OutputValue]"

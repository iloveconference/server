#!/usr/bin/env bash
# The one-time bootstrap around stack "ilc", run by hand with admin credentials:
#   1. edge         stack ilc-edge (us-east-1, edge.yaml): certificate, alarms topic, budget
#   2. github       stack ilc-github (us-west-2, github.yaml): artifacts bucket, permissions
#                   boundary, ilc-cfn-exec, ilc-server-deploy
#   3.              stack ilc: scripts/deploy-manual.sh
#   4. edge-alarm   stack ilc-edge again, with ilc's DistributionId (adds the CloudFront 5xx alarm)
#   5. github-vars  GitHub Actions variables for the server and client repos (needs gh)
#
# Usage:
#   scripts/bootstrap.sh              print the commands for every step (the default)
#   scripts/bootstrap.sh --run STEP   run one step: edge, github, edge-alarm or github-vars
#
# Environment:
#   ALERT_EMAIL  overrides the AlertEmail parameter of ilc-edge (default dallan@genefun.com)
#
# Values that come from stack outputs are looked up when the stacks exist; otherwise the
# printed commands show a <placeholder>.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Prints the header comment above.
usage() {
	awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}" >&2
	exit 2
}

# Prints output KEY of stack STACK in REGION, or <placeholder> if it can't be read.
stack_output() {
	local value
	value="$(aws cloudformation describe-stacks --stack-name "$1" --region "$2" --output text \
		--query "Stacks[0].Outputs[?OutputKey=='$3'].OutputValue | [0]" 2>/dev/null || true)"
	if [[ -z "$value" || "$value" == None ]]; then
		value="<$3 output of stack $1>"
	fi
	printf '%s\n' "$value"
}

# Prints a command. Its arguments (ARNs, IDs, names) never contain spaces, so it pastes as is.
show() {
	printf '  %s\n' "$*"
}

# Runs a command after printing it, refusing commands that still hold a <placeholder>.
run() {
	local arg
	for arg in "$@"; do
		if [[ "$arg" == *"<"*">"* ]]; then
			echo "bootstrap.sh: missing value: $arg" >&2
			exit 1
		fi
	done
	show "$@"
	"$@"
}

edge_overrides=()
if [[ -n "${ALERT_EMAIL:-}" ]]; then
	edge_overrides=(--parameter-overrides "AlertEmail=$ALERT_EMAIL")
fi

edge() {
	"$1" aws cloudformation deploy --region us-east-1 --stack-name ilc-edge \
		--template-file edge.yaml --tags project=ilc --no-fail-on-empty-changeset \
		${edge_overrides[@]+"${edge_overrides[@]}"}
}

github() {
	"$1" aws cloudformation deploy --region us-west-2 --stack-name ilc-github \
		--template-file github.yaml --capabilities CAPABILITY_NAMED_IAM --tags project=ilc \
		--no-fail-on-empty-changeset
}

# Parameters left out keep their previous values, so AlertEmail is unchanged.
edge_alarm() {
	"$1" aws cloudformation deploy --region us-east-1 --stack-name ilc-edge \
		--template-file edge.yaml --tags project=ilc --no-fail-on-empty-changeset \
		--parameter-overrides "DistributionId=$(stack_output ilc us-west-2 DistributionId)"
}

github_vars() {
	local server=iloveconference/server client=iloveconference/client
	"$1" gh variable set AWS_SERVER_DEPLOY_ROLE_ARN --repo "$server" \
		--body "$(stack_output ilc-github us-west-2 ServerDeployRoleArn)"
	"$1" gh variable set AWS_CFN_EXEC_ROLE_ARN --repo "$server" \
		--body "$(stack_output ilc-github us-west-2 CfnExecRoleArn)"
	"$1" gh variable set SAM_ARTIFACTS_BUCKET --repo "$server" \
		--body "$(stack_output ilc-github us-west-2 ArtifactsBucketName)"
	"$1" gh variable set PERMISSIONS_BOUNDARY_ARN --repo "$server" \
		--body "$(stack_output ilc-github us-west-2 PermissionsBoundaryArn)"
	"$1" gh variable set CERTIFICATE_ARN --repo "$server" \
		--body "$(stack_output ilc-edge us-east-1 CertificateArn)"
	"$1" gh variable set AWS_CLIENT_DEPLOY_ROLE_ARN --repo "$client" \
		--body "$(stack_output ilc us-west-2 ClientDeployRoleArn)"
}

print_all() {
	cat <<'EOF'
Bootstrap for iloveconference.org (run each step once, in order, with admin credentials).
Nothing below has been run. To run a step: scripts/bootstrap.sh --run STEP

Step 1 (edge): certificate, alarms topic and budget in us-east-1. CloudFormation waits until
the certificate is ISSUED; it validates through the existing ACM CNAMEs. Then confirm the SNS
subscription email, and activate the "project" cost allocation tag (Billing console) so the
budget sees costs.
EOF
	edge show
	cat <<'EOF'

Step 2 (github): artifacts bucket, permissions boundary and deploy roles in us-west-2.
EOF
	github show
	cat <<'EOF'

Step 3: the first deploy of stack ilc, by hand, through ilc-cfn-exec. Confirm the ilc-alerts
SNS subscription email afterwards.
  scripts/deploy-manual.sh

Step 4 (edge-alarm): add the CloudFront 5xx alarm now that the distribution exists.
EOF
	edge_alarm show
	cat <<'EOF'

Step 5 (github-vars): GitHub Actions variables (not secrets) for both repos.
EOF
	github_vars show
}

if [[ $# -eq 0 ]]; then
	print_all
	exit 0
fi
if [[ $# -ne 2 || "$1" != --run ]]; then
	usage
fi
case "$2" in
edge) edge run ;;
github) github run ;;
edge-alarm) edge_alarm run ;;
github-vars) github_vars run ;;
*) usage ;;
esac

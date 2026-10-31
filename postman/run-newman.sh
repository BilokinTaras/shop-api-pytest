#!/bin/sh
# Runs the Postman smoke collection with values from the shop-sut contract file (no secrets on disk).
set -eu
cd "$(dirname "$0")"
ENV_FILE=${SUT_ENV_FILE:-../../shop-sut/.generated/sut.env}
val() { grep "^$1=" "$ENV_FILE" | cut -d= -f2-; }
mkdir -p ../reports/newman
npx newman run shop-smoke.postman_collection.json \
  -e shop.postman_environment.template.json \
  --env-var "base_url=$(val SUT_BACKEND_URL)" \
  --env-var "publishable_key=$(val SUT_PUBLISHABLE_KEY)" \
  --env-var "region_id=$(val SUT_REGION_ID)" \
  --env-var "admin_email=$(val SUT_ADMIN_EMAIL)" \
  --env-var "admin_password=$(val SUT_ADMIN_PASSWORD)" \
  --reporters cli,junit,htmlextra \
  --reporter-junit-export ../reports/newman/junit.xml \
  --reporter-htmlextra-export ../reports/newman/report.html

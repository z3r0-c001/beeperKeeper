#!/bin/bash
#
# Sanitization Verification Script for BeeperKeeper
# Run this script before pushing to GitHub to ensure no sensitive data is present
#
# Usage: ./verify_sanitization.sh
# Exit code: 0 = all checks pass, 1 = sensitive data found

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo " BEEPERKEEPER SANITIZATION AUDIT"
echo "======================================"
echo ""
echo "Location: $SCRIPT_DIR"
echo "Date: $(date)"
echo ""

FAILED_CHECKS=0

# Function to run a check
run_check() {
    local check_name="$1"
    local pattern="$2"
    local includes="${3:-}"

    echo -n "Checking: $check_name... "

    if [ -n "$includes" ]; then
        if grep -r "$pattern" $includes . 2>/dev/null | grep -v "verify_sanitization.sh" > /dev/null; then
            echo "❌ FAIL"
            echo "  Found sensitive data:"
            grep -r "$pattern" $includes . 2>/dev/null | grep -v "verify_sanitization.sh" | head -5
            echo ""
            FAILED_CHECKS=$((FAILED_CHECKS + 1))
            return 1
        fi
    else
        if grep -r "$pattern" . 2>/dev/null | grep -v "verify_sanitization.sh" > /dev/null; then
            echo "❌ FAIL"
            echo "  Found sensitive data:"
            grep -r "$pattern" . 2>/dev/null | grep -v "verify_sanitization.sh" | head -5
            echo ""
            FAILED_CHECKS=$((FAILED_CHECKS + 1))
            return 1
        fi
    fi

    echo "✅ PASS"
    return 0
}

echo "=== CRITICAL CREDENTIALS CHECKS ==="
echo ""

# Check 1: WiFi Password
run_check "WiFi password" "U_2181Kha"

# Check 2: InfluxDB Password
run_check "InfluxDB password 'beeperkeeper2024'" "beeperkeeper2024"

# Check 3: Grafana Password
run_check "Grafana password 'beeperkeeper'" "ADMIN_PASSWORD=beeperkeeper"

# Check 4: InfluxDB Production Token
run_check "InfluxDB production token" "eCxn7YDEeZ8Xfwic"

# Check 5: Personal Emails
run_check "Personal email addresses" "nicolezspence@gmail\.com\|david\.yuppa@gmail\.com"

echo ""
echo "=== STANDARD SANITIZATION CHECKS ==="
echo ""

# Check 6: Private IPs
run_check "Private IP addresses (172.16.x.x)" "172\.16\." "--include='*.py' --include='*.md' --include='*.yml' --include='*.html' --include='*.js' --include='*.conf' --include='*.ino'"

# Check 7: Domain Names
run_check "Domain names (goodsupply.farm)" "goodsupply" "--include='*.py' --include='*.md' --include='*.yml' --include='*.html' --include='*.conf' --include='*.ino'"

# Check 8: Real Usernames
run_check "Real usernames" "binhex\|great_ape\|tameg\|tamegorilla\|z3r0-c001" "--include='*.py' --include='*.md' --include='*.yml' --include='*.html' --include='*.conf'"

echo ""
echo "=== INTERNAL FILES CHECK ==="
echo ""

# Check for internal documentation that shouldn't be public
INTERNAL_FILES=(
    "CLAUDE.md"
    "SANITIZATION_SUMMARY.md"
    "SANITIZATION_COMPLETE.md"
    "SESSION_SUMMARY_*.md"
    "SYNC_REPORT_*.md"
    "V2_SYNC_STATUS.md"
    "V2_PRODUCTION_NOTES.md"
)

for file_pattern in "${INTERNAL_FILES[@]}"; do
    if ls $file_pattern 2>/dev/null | grep -v "verify_sanitization.sh" > /dev/null; then
        echo "❌ FAIL: Found internal file: $file_pattern"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    fi
done

if [ $FAILED_CHECKS -eq 0 ]; then
    echo "✅ No internal documentation files found"
fi

echo ""
echo "======================================"
echo " AUDIT RESULTS"
echo "======================================"
echo ""

if [ $FAILED_CHECKS -eq 0 ]; then
    echo "✅ ALL CHECKS PASSED"
    echo ""
    echo "Repository is safe to push to GitHub."
    echo "Total checks: 8 + internal files"
    echo "Failed checks: 0"
    echo ""
    exit 0
else
    echo "❌ AUDIT FAILED"
    echo ""
    echo "⚠️  DO NOT PUSH TO GITHUB ⚠️"
    echo ""
    echo "Failed checks: $FAILED_CHECKS"
    echo "Please sanitize the sensitive data before pushing."
    echo ""
    echo "Common fixes:"
    echo "1. Replace WiFi password with 'YOUR_WIFI_PASSWORD'"
    echo "2. Replace database passwords with environment variables: \${INFLUXDB_PASSWORD:-change-this-password}"
    echo "3. Replace tokens with 'YOUR_INFLUXDB_TOKEN_HERE'"
    echo "4. Replace personal emails with 'user@example.com'"
    echo "5. Replace 172.16.0.7 with 10.10.10.7, 172.16.0.28 with 10.10.10.28"
    echo "6. Replace goodsupply.farm with YOUR_DOMAIN/YOUR_WEBSITE"
    echo "7. Replace real usernames (binhex, great_ape, tameg) with placeholders (pi_user, dev_user, user)"
    echo "8. Remove internal documentation files (CLAUDE.md, etc.)"
    echo ""
    exit 1
fi

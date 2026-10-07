# Shared borrow-request access selection for setup.sh.

ask_request_access() {
  # Asked here with the other identity questions, applied at the very END of setup: the
  # answer implies the `membership` module, the module list is chosen after the app is
  # running, and the real state can only be read back from the database once both have
  # been applied. See apply_request_access.
  echo
  echo "Who can submit borrow requests?"
  echo "  1) Members only            - people you have enrolled as members of this makerspace"
  echo "  2) Anyone with an account  - any signed-in user; staff still accept every request"
  echo "  3) Anyone, no account      - a stranger leaves their name and contact details"
  echo "  4) Anyone on your check-in roster - no account; verified against your check-in API"
  echo "Option 3 is an unauthenticated write surface: it is rate limited, contact details are"
  echo "marked unverified, and no email is sent to them until you verify. You can change this"
  echo "later with 'manage.py set_request_access'."
  echo "Option 4 checks a typed name against a PUBLIC check-in roster. A match proves that name"
  echo "is checked in at your space, not who is typing: anyone can enter another checked-in"
  echo "person's name. Staff still accept every request and record hand-over evidence."
  echo "See 'Check-in gated requests' in docs/INVARIANTS.md."
  read -r -p "Choice [2]: " REQUEST_ACCESS_CHOICE
  case "${REQUEST_ACCESS_CHOICE:-2}" in
    1) REQUEST_ACCESS=members ;;
    3) REQUEST_ACCESS=anyone ;;
    4) ask_checkin_settings ;;
    2) REQUEST_ACCESS=accounts ;;
    *) warn "Unrecognised choice; requiring an account."; REQUEST_ACCESS=accounts ;;
  esac
}

ask_checkin_settings() {
  local url space_id purpose reason=""
  local url_pattern='^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/?&=%:+-]*)?$'
  IFS= read -r -p "Check-in API URL (https://...): " url || url=""
  IFS= read -r -p "Your space id in the check-in system: " space_id || space_id=""
  IFS= read -r -p "Required check-in purpose [Working on a project]: " purpose || purpose=""
  purpose="${purpose#"${purpose%%[![:space:]]*}"}"
  purpose="${purpose%"${purpose##*[![:space:]]}"}"
  purpose="${purpose:-Working on a project}"

  if [[ ! "$url" =~ $url_pattern ]]; then
    reason="Invalid check-in API URL: use http:// or https:// with a host and no spaces."
  elif ! env_value_is_safe "$url"; then
    reason="Check-in API URL contains characters unsafe for .env."
  elif [[ ! "$space_id" =~ ^[1-9][0-9]{0,9}$ ]]; then
    reason="Invalid check-in space id: use a positive integer of at most 10 digits."
  elif (( 10#$space_id > 2147483647 )); then
    reason="Invalid check-in space id: the maximum is 2147483647."
  elif ! env_value_is_safe "$purpose"; then
    reason="Required check-in purpose contains characters unsafe for .env."
  fi
  if [[ -n "$reason" ]]; then
    warn "$reason Falling back to: an account is required."
    REQUEST_ACCESS=accounts
    CHECKIN_URL_INPUT=""; CHECKIN_SPACE_ID_INPUT=""; CHECKIN_PURPOSE_INPUT=""
    return 0
  fi

  CHECKIN_URL_INPUT="$url"
  CHECKIN_SPACE_ID_INPUT="$space_id"
  CHECKIN_PURPOSE_INPUT="$purpose"
  REQUEST_ACCESS=checked_in
  # The checkin profile starts the space with the full inventory lifecycle, reports
  # and every machines module.
  MSPROFILE=checkin
}

persist_checkin_settings() {
  if [[ "${REQUEST_ACCESS:-}" == checked_in ]]; then
    if ! env_file_append_if_absent .env CHECKIN_API_URL "$CHECKIN_URL_INPUT" \
      || ! env_file_append_if_absent .env CHECKIN_REQUIRED_PURPOSE "$CHECKIN_PURPOSE_INPUT"; then
      warn "Could not persist check-in settings. Falling back to: an account is required."
      REQUEST_ACCESS=accounts
    fi
  fi
  return 0
}

choose_modules() {
  MODULE_MODE=interactive
  MODULE_INTERACTIVE=1
  MODULE_MAKERSPACE=""
  MODULE_ALL_MAKERSPACES=0
  MODULE_WITHOUT=""
  MODULE_CONFIRM_REMOVALS=0
  # The borrow-request answer IS the membership module, so the tick list opens with it
  # already set that way. The operator can still change it -- and if they do, the
  # read-back in apply_request_access wins, not the answer they gave earlier.
  MODULE_FORCE_ON=""
  MODULE_FORCE_OFF=""
  case "${REQUEST_ACCESS:-}" in
    members)          MODULE_FORCE_ON="membership" ;;
    accounts|anyone)  MODULE_FORCE_OFF="membership" ;;
    checked_in)
      # The owner wants reports, Telegram alerts, staff hand-over, and all machine
      # modules on a check-in deployment; the request workflow and staff ledger
      # are core and always on.
      MODULE_FORCE_ON="reports,telegram,guest_handover,machines,machine_service,printing,maintenance"
      MODULE_FORCE_OFF="membership"
      ;;
  esac
  change_modules
}

# Deliberately AFTER choose_modules, and it re-reads the database rather than trusting
# $REQUEST_ACCESS. The operator may have ticked `membership` back on in the list above,
# and `membership` makes account-less requests impossible -- so the answer given three
# questions ago is a request, not the truth. Fail closed: if the flag cannot be opened,
# submission stays behind an account rather than being left open by accident.
apply_request_access() {
  local slug="$1" mode="${REQUEST_ACCESS:-accounts}" retry_command
  if [[ "$mode" == checked_in ]]; then
    if "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py set_request_access --makerspace "$slug" --mode checked_in \
      --checkin-space-id "$CHECKIN_SPACE_ID_INPUT"; then
      return 0
    fi
    warn "Check-in borrow requests were NOT enabled (the membership module may be on, or the check-in settings were rejected)."
    warn "Borrow requests will require an account. Fix the settings or turn membership off and re-run:"
    printf -v retry_command '%q ' "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py set_request_access --makerspace "$slug" --mode checked_in \
      --checkin-space-id "$CHECKIN_SPACE_ID_INPUT"
    warn "  $retry_command"
    mode=accounts
  fi
  if [[ "$mode" == anyone ]]; then
    if ! "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py set_request_access --makerspace "$slug" --mode anyone; then
      warn "Account-less borrow requests were NOT enabled (the membership module is on)."
      warn "Borrow requests will require an account. Turn membership off and re-run:"
      warn "  ${COMPOSE[*]} run --rm --no-deps backend --role management python manage.py set_request_access --mode anyone"
      mode=members
    else
      return 0
    fi
  fi
  "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py set_request_access --makerspace "$slug" --mode "$mode" \
    || warn "Could not set who may submit borrow requests; the default (account required) stands."
}

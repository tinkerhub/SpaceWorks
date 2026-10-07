# Shared non-executable Compose env-file parsing and host schedule validation.

# Normalise one line the way backup/host_topology_record.py does (surrounding
# whitespace, one optional "export " prefix) so "present" means the same thing here,
# to the topology record's duplicate-key check, and to the reader below.
_env_file_assignment() {
  local line="${1%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  [[ "$line" == "export "* ]] && line="${line#export }"
  printf '%s' "$line"
}

env_file_has_key() {
  local file="$1" key="$2" line
  [[ -f "$file" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$(_env_file_assignment "$line")" == "$key="* ]] && return 0
  done < "$file"
  return 1
}

env_file_get() {
  local file="$1" key="$2" line value
  [[ -e "$file" ]] || return 0
  [[ -f "$file" && -r "$file" ]] || {
    printf 'ERROR: cannot read env file: %s\n' "$file" >&2; return 1
  }
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(_env_file_assignment "$line")"
    [[ "$line" == "$key="* ]] || continue
    value="${line#*=}"
    # Compose env-file rules: a quoted value ends at its closing quote (anything
    # after it is a comment); in an unquoted value only whitespace followed by #
    # starts a comment, so KEY=#x is the literal "#x"; the rest is trimmed.
    if [[ "$value" =~ ^[[:space:]]+# ]]; then
      value=""
    else
      value="${value#"${value%%[![:space:]]*}"}"
      if [[ "$value" =~ ^\"([^\"]*)\" || "$value" =~ ^\'([^\']*)\' ]]; then
        value="${BASH_REMATCH[1]}"
      else
        # %% removes the longest suffix, i.e. from the FIRST whitespace-then-#.
        value="${value%%[[:space:]]#*}"
        value="${value%"${value##*[![:space:]]}"}"
      fi
    fi
    printf '%s\n' "$value"
    return 0
  done < "$file" || {
    printf 'ERROR: cannot read env file: %s\n' "$file" >&2; return 1
  }
  return 0
}

env_value_is_safe() {
  local value="$1" LC_ALL=C
  case "$value" in
    ''|[[:space:]]*|*[[:space:]]|*$'\r'*|*$'\n'*|*'$'*|*'#'*|*"'"*|*'"'*|*'\'*|*'`'*)
      printf 'ERROR: unsafe env value: empty, surrounding whitespace, or forbidden character.\n' >&2
      return 1
      ;;
  esac
  return 0
}

env_file_append_if_absent() {
  local file="$1" key="$2" value="$3" last LC_ALL=C
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || {
    printf 'ERROR: invalid env key: %s\n' "$key" >&2; return 1
  }
  env_value_is_safe "$value" || return 1
  if [[ -e "$file" ]]; then
    [[ -f "$file" && -r "$file" ]] || {
      printf 'ERROR: cannot read env file: %s\n' "$file" >&2; return 1
    }
    env_file_has_key "$file" "$key" && return 0
    if [[ -s "$file" ]]; then
      last="$(tail -c 1 "$file")" || {
        printf 'ERROR: cannot read env file ending: %s\n' "$file" >&2; return 1
      }
      if [[ -n "$last" ]]; then
        printf '\n' >> "$file" || {
          printf 'ERROR: cannot append newline to env file: %s\n' "$file" >&2; return 1
        }
      fi
    fi
  fi
  printf '%s=%s\n' "$key" "$value" >> "$file" || {
    printf 'ERROR: cannot append env key to: %s\n' "$file" >&2; return 1
  }
}

validate_cron_schedule() {
  local schedule="$1" field item base step number normalized index=0
  local LC_ALL=C IFS=$' \t'
  local -a fields items numbers minimum=(0 0 1 1 0) maximum=(59 23 31 12 7)
  if [[ "$schedule" == *$'\r'* || "$schedule" == *$'\n'* || "$schedule" == *'%'* ]]; then
    printf 'ERROR: cron schedule cannot contain CR, LF, or %%.\n' >&2; return 1
  fi
  schedule="${schedule//$'\v'/ }"; schedule="${schedule//$'\f'/ }"
  read -r -a fields <<< "$schedule"
  [[ ${#fields[@]} == 5 ]] || {
    printf 'ERROR: cron schedule must contain exactly five fields.\n' >&2; return 1
  }
  for field in "${fields[@]}"; do
    if [[ "$field" == ,* || "$field" == *, || "$field" == *,,* ]]; then
      printf 'ERROR: cron fields cannot contain empty list items.\n' >&2; return 1
    fi
    IFS=, read -r -a items <<< "$field"
    for item in "${items[@]}"; do
      [[ "$item" =~ ^(\*|[0-9]+|[0-9]+-[0-9]+)(/([0-9]+))?$ ]] || {
        printf 'ERROR: invalid cron item: %s\n' "$item" >&2; return 1
      }
      base="${BASH_REMATCH[1]}"; step="${BASH_REMATCH[3]}"
      if [[ "$item" == */* && ! "$step" =~ ^0*[1-9][0-9]*$ ]]; then
        printf 'ERROR: cron step must be a positive integer.\n' >&2; return 1
      fi
      [[ "$base" == '*' ]] && continue
      IFS=- read -r -a numbers <<< "$base"
      for number in "${numbers[@]}"; do
        # Strip zeros before arithmetic so long inputs cannot overflow into valid bounds.
        normalized="${number#"${number%%[!0]*}"}"; normalized="${normalized:-0}"
        if (( ${#normalized} > 2 )) \
          || (( 10#$normalized < minimum[index] || 10#$normalized > maximum[index] )); then
          printf 'ERROR: cron value is outside field bounds: %s\n' "$number" >&2; return 1
        fi
      done
      if [[ ${#numbers[@]} == 2 ]] && (( 10#${numbers[0]} > 10#${numbers[1]} )); then
        printf 'ERROR: cron range must be ascending: %s\n' "$base" >&2; return 1
      fi
    done
    index=$((index + 1))
  done
  printf '%s %s %s %s %s\n' "${fields[@]}"
}

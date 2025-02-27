#!/usr/bin/env bash

set -e

EXTRA_OPTIONS=""

while [ -n "$1" ]
do
   case "$1" in
        "--open" )
            EXTRA_OPTIONS="$EXTRA_OPTIONS $1"
            ;;

        *)
            echo "Unknown param : $1"
            exit 1
            ;;
   esac
   shift
done


MD_FILES=$(find ./*.md use_case_examples docs -type f -name "*.md")

# shellcheck disable=SC2086
poetry run python script/doc_utils/check_forbidden_words.py --files $MD_FILES $EXTRA_OPTIONS



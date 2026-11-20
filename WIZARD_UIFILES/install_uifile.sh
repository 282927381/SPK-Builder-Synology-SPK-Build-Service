#!/bin/bash

page_append ()
{
    if [ -z "$1" ]; then
        echo "$2"
    elif [ -z "$2" ]; then
        echo "$1"
    else
        echo "$1,$2"
    fi
}

PAGE_OUTPUT_FOLDER=$(/bin/cat<<EOF
{
    "step_title": "Output folder",
    "invalid_next_disabled_v2": true,
    "items": [{
        "type": "textfield",
        "desc": "Please select a shared folder for storing built .spk packages. If this folder doesn't exist at the time of installation, it will be created.",
        "subitems": [{
            "key": "wizard_shared_folder_name",
            "desc": "Shared folder",
            "defaultValue": "spkbuilder",
            "validator": {
                "allowBlank": false,
                "regex": {
                    "expr": "/^[\\\w.][\\\w. -]{0,30}[\\\w.-][\\\\$]?$|^[\\\w][\\\\$]?$/",
                    "errorText": "Subdirectories are not supported."
                }
            }
        }]
    }]
}
EOF
)

main () {
    local install_page=""
    install_page=$(page_append "$install_page" "$PAGE_OUTPUT_FOLDER")
    echo "[$install_page]" > "${SYNOPKG_TEMP_LOGFILE}"
}

main "$@"

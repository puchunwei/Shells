function _ccswitch_normalize_model --description "Normalize a model ID for the configured gateway"
    set -l backend (dirname (status --current-filename))/ccswitch_backend.py
    set -lx MODEL "$argv[1]"
    python3 "$backend" normalize-model
end

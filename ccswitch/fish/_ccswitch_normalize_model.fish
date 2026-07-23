function _ccswitch_normalize_model --description "Append the [1m] (1M context) suffix to a model name if it's missing"
    set -l m "$argv[1]"
    if test -n "$m"
        if not string match -rq '\[1m\]' "$m"
            set m "$m"\[1m\]
        end
    end
    printf '%s' "$m"
end

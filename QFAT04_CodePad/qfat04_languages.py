"""
qfat04_languages.py
Highlighter / Lexer Registry.

Priority table (higher number wins — both BasicHighlighter and TuflowLexer
use the same scheme so behaviour is identical on both backends):

   1  operator        – ==, >, <, |, +, -, *, /
   2  number          – \d+, floats
   3  string          – delimiters defined in language
   4  command         – text before == on a TUFLOW line
   5  keyword group 1 – user-defined Group 1
   6  keyword group 2 – user-defined Group 2
   7  keyword group 3 – user-defined Group 3
   8  keyword group 4 – user-defined Group 4
   9  keyword group 5 – user-defined Group 5
  15  path            – file/folder paths  (beats all keywords)
  20  comment         – always wins

Design notes
------------
* Path is priority 15 so that any keyword or operator colour that happens to
  land on a path token (e.g. "gis" inside "..\model\gis\...") is overwritten.
* Command (4) is intentionally LOWER than keyword groups so that if the user
  puts a command-name phrase in a keyword group it gets the keyword group
  colour, not the command colour — matching Notepad++ behaviour.
* Each keyword group has its own distinct priority so group1 tokens can never
  be recoloured by group2, group3, etc., and vice-versa.
* Comments win over everything including paths (inline trailing comments).
"""

import re




from qgis.PyQt.QtGui import QColor, QFont, QTextCharFormat, QSyntaxHighlighter

from .qfat04_config import (
    get_theme,
    get_factory_theme,
    style_color,
    style_paper,
    style_font,
    language_style,
    DEFAULT_HIGHLIGHT_PRIORITIES,
)

# ---------------------------------------------------------------------------
# QScintilla optional import
# ---------------------------------------------------------------------------
TRY_QSCI = True
try:
    from qgis.PyQt.Qsci import QsciScintilla, QsciLexerCustom
except Exception:
    TRY_QSCI = False
    QsciScintilla = None
    QsciLexerCustom = object

# ---------------------------------------------------------------------------
# Token-type style keys
# ---------------------------------------------------------------------------
ALL_STYLE_KEYS = [
    "text", "comment",
    "keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6",
    "number", "string", "operator", "path", "folding", "variable",
]

# Priority keys — names match config["highlight_priorities"] keys
_P_KEYS = ["operator", "number", "string", "command",
           "keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6",
           "path", "comment", "variable"]


def _priorities(config, lang_def=None):
    """
    Return the priority dict for this language.
    Reads lang_def["highlight_priorities"], falls back to DEFAULT_HIGHLIGHT_PRIORITIES.
    Always guarantees comment > all other values.
    """
    base = dict(DEFAULT_HIGHLIGHT_PRIORITIES)
    user = lang_def.get("highlight_priorities") if isinstance(lang_def, dict) else None
    if isinstance(user, dict):
        for k in _P_KEYS:
            v = user.get(k)
            if v is not None:
                try:
                    iv = int(v)
                    if iv >= 0:
                        base[k] = iv
                except (TypeError, ValueError):
                    pass
    # Enforce comment is always the maximum
    max_non = max(v for k, v in base.items() if k != "comment")
    if base["comment"] <= max_non:
        base["comment"] = max_non + 1
    return base


# ---------------------------------------------------------------------------
# Language definition helpers
# ---------------------------------------------------------------------------

def _lang_def(config, language_key):
    """Return the effective language definition, respecting per-tab override modes.
    Mode 0/1: use factory .json values for that tab's fields.
    Mode 2: use QSettings merged values (current behavior).
    """
    merged = (config.get("languages") or {}).get(language_key, {})
    if not isinstance(merged, dict):
        return {}
    overrides = merged.get("_tab_overrides", {})
    if not overrides:
        return merged  # no override info, use merged as-is

    # Check if any tab is non-custom (mode 0 or 1)
    has_factory = any(v in (0, 1) for v in overrides.values() if isinstance(v, int))
    if not has_factory:
        # Check for old bool format: False = non-custom
        has_factory = any(v is False for v in overrides.values())
    if not has_factory:
        return merged  # all tabs are custom, use merged as-is

    # Load factory defaults from .json
    from .qfat04_config import language_json_path, _norm_ext_list
    import json as _json
    factory = {}
    json_path = language_json_path(language_key)
    if json_path:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                factory = _json.load(f)
        except Exception as e:
            import traceback
            traceback.print_exc()  # prints to QGIS Python console

    if not factory:
        return merged  # no .json file, use merged

    # Tab → fields mapping
    _TAB_FIELDS = {
        "general":    ["extensions", "case_sensitive"],
        "keywords":   ["keyword_groups", "keywords", "prefix_modes", "keyword_group_styles"],
        "comments":   ["comment_prefixes", "comment_position", "fold_comments",
                       "comment_continue", "comment_close",
                       "block_comment_open", "block_comment_close"],
        "numbers":    ["number_style"],
        "operators":  ["operators1", "operators2", "operators3", "operators4", "operators5", "operators6"],
        "delimiters": ["delimiters"],
        "folding":    ["folding"],
        "path":       ["path_pattern"],
        "variables":  ["variable_patterns"],
    }

    # Build effective definition
    result = dict(merged)
    for tab_key, fields in _TAB_FIELDS.items():
        mode = overrides.get(tab_key, 2)
        if isinstance(mode, bool):
            mode = 2 if mode else 1  # backward compat
        if mode in (0, 1):
            # Use factory values for these fields
            for field in fields:
                if field in factory:
                    val = factory[field]
                    if field == "extensions":
                        val = _norm_ext_list(val)
                    result[field] = val
                elif field in result:
                    # Factory doesn't have it — remove from result so defaults apply
                    del result[field]

    return result


def _case_flags(lang_def):
    return 0 if bool(lang_def.get("case_sensitive", False)) else re.IGNORECASE


def _split_ws_tokens(text):
    return [t for t in re.split(r"[\s,]+", str(text or "").strip()) if t]


def _keyword_pattern(tok, prefix_mode=False):
    """
    Build a regex for *tok*.

    Multi-word phrases like "read gis mat" are matched as whole phrases.
    Tokens that start/end with word characters get \b anchors.
    Tokens made entirely of non-word characters (e.g. "==", ">>") get
    plain re.escape — adding \b would prevent any match because \b
    requires a word/non-word boundary which "=" never has.
    """
    et = re.escape(tok)
    if prefix_mode:
        return r"\b" + et + r"[A-Za-z0-9_]*\b"
    # Check whether the token starts/ends with a word character
    starts_word = bool(re.match(r'\w', tok[0]))   if tok else False
    ends_word   = bool(re.match(r'\w', tok[-1]))  if tok else False
    prefix = r"\b" if starts_word else r"(?<![\w])" if not starts_word else ""
    suffix = r"\b" if ends_word   else r"(?![\w])"  if not ends_word   else ""
    # For purely symbolic tokens like == >> << just use plain escape (no boundary needed)
    if not starts_word and not ends_word:
        return et
    return prefix + et + suffix


def _comment_patterns(lang_def, base):
    """Return list of raw pattern strings for comment recognition.
    Key absent → Tier 2 fallback.  Key present + empty → disabled.
    """
    if not isinstance(lang_def, dict):
        return []
    if "comment_prefixes" in lang_def:
        # Key present — use it (even if empty = disabled)
        prefixes = [str(x) for x in lang_def["comment_prefixes"] if str(x).strip()]
        if not prefixes:
            return []
    else:
        # Key absent — Tier 2 fallback
        defaults = {
            "tuflow":     ["!"],
            "powershell": ["#"],
            "batch":      ["REM", "::"],
            "python":     ["#"],
            "r":          ["#"],
            "sql":        ["--"],
            "html":       ["<!--"],
        }
        prefixes = defaults.get(base, [])
        if not prefixes:
            return []
    pos  = str(lang_def.get("comment_position", "anywhere"))
    pats = []
    for pref in prefixes:
        ep = re.escape(pref)
        if pos == "start":
            pats.append(r"^" + ep + r".*$")
        elif pos == "whitespace":
            pats.append(r"^\s*" + ep + r".*$")
        else:
            pats.append(ep + r".*$")
    return pats


def _keyword_groups(lang_def):
    groups = lang_def.get("keyword_groups") if isinstance(lang_def, dict) else []
    if not isinstance(groups, list):
        return [""] * 6
    vals = []
    for x in groups[:6]:
        # Accept list-of-strings (preferred, avoids long-string entropy flags)
        # or legacy newline-joined string.
        if isinstance(x, list):
            vals.append("\n".join(str(s) for s in x))
        else:
            vals.append(str(x))
    return vals + [""] * (6 - len(vals))


def _group_styles(lang_def):
    styles = lang_def.get("keyword_group_styles") if isinstance(lang_def, dict) else []
    out = []
    if isinstance(styles, list):
        out = [str(x).strip() or ("keyword%d" % (i + 1)) for i, x in enumerate(styles[:6])]
    return out + ["keyword%d" % (i + 1) for i in range(len(out), 6)]


def _tokens_from_group(text):
    """
    One entry per non-blank line.
    Each LINE is one complete phrase — spaces are part of the phrase.
    "read gis mat" on one line → one token → matched as the whole phrase.
    Never split by spaces so bare sub-words like "gis" are never matched.
    """
    vals = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        tok = raw.strip()
        if tok:
            vals.append(tok)
    return vals


def _operator_tokens(lang_def, base):
    """Return operator token list.
    Key absent → Tier 2 fallback.  Key present + empty → disabled.
    """
    default_map = {
        "tuflow":     ["|"],
        "powershell": ["-eq", "-ne", "-gt", "-lt", "=", "+", "-", "*", "/"],
        "batch":      ["==", "equ", "neq", "geq", "leq", "gtr", "lss"],
    }
    if not isinstance(lang_def, dict):
        return []
    if "operators1" in lang_def:
        # Key present — use it (even if empty = disabled)
        tokens = _split_ws_tokens(str(lang_def["operators1"]).replace(",", " "))
    else:
        # Key absent — Tier 2 fallback
        tokens = list(default_map.get(base, []))
    user_op2 = lang_def.get("operators2", "")
    if user_op2:
        tokens.extend(_split_ws_tokens(str(user_op2).replace(",", " ")))
    out = []
    for t in sorted(set(tokens), key=lambda x: (-len(x), x)):
        if t:
            out.append(t)
    return out


def _delimiter_patterns(lang_def):
    out = []
    if isinstance(lang_def, dict):
        for d in (lang_def.get("delimiters") or []):
            if not isinstance(d, dict):
                continue
            op  = str(d.get("open",   ""))
            cl  = str(d.get("close",  ""))
            esc = str(d.get("escape", ""))
            if not op:
                continue
            eop = re.escape(op)
            if cl:
                ecl = re.escape(cl)
                if esc:
                    eesc = re.escape(esc)
                    out.append(eop + r"(?:[^\n]|" + eesc + r".)*?" + ecl)
                else:
                    out.append(eop + r".*?" + ecl)
            else:
                out.append(eop + r"[^\s]*")
    return out


def _number_pattern(lang_def):
    """Return regex for number detection.
    Key absent → no detection.  Key present + empty/False → no detection.
    Key present + valid dict → build pattern from fields.
    """
    if not isinstance(lang_def, dict):
        return None
    if "number_style" not in lang_def:
        return None  # Key absent — no number detection
    ns = lang_def["number_style"]
    if not ns or not isinstance(ns, dict):
        return None  # key present but empty = disabled
    dec = str(ns.get("decimal", "dot"))
    if dec == "none":
        return None  # explicitly disabled
    if dec == "comma":
        dec_re = r",\d+"
    elif dec == "both":
        dec_re = r"[\.,]\d+"
    else:
        dec_re = r"\.\d+"

    # Extras: additional characters allowed inside a number
    extras1 = str(ns.get("extras1", "")).strip()
    extras2 = str(ns.get("extras2", "")).strip()
    if extras1 or extras2:
        extra_chars = re.escape(extras1 + extras2)
        digit_class = r"[\d" + extra_chars + r"]"
    else:
        digit_class = r"\d"
    core = digit_class + r"+(?:" + dec_re + r")?"

    prefixes = [re.escape(x) for x in [str(ns.get("prefix1", "")).strip(), str(ns.get("prefix2", "")).strip()] if x]
    suffixes = [re.escape(x) for x in [str(ns.get("suffix1", "")).strip(), str(ns.get("suffix2", "")).strip()] if x]
    pre = r"(?:" + "|".join(prefixes) + r")?" if prefixes else ""
    suf = r"(?:" + "|".join(suffixes) + r")?" if suffixes else ""

    single = pre + core + suf

    # Range: character connecting two numbers (e.g. '-' for 1-10)
    range_ch = str(ns.get("range", "")).strip()
    if range_ch:
        return single + r"(?:" + re.escape(range_ch) + single + r")?"
    return single



def _variable_pattern_to_regex(pattern_str):
    """
    Convert a user-friendly pattern string to a regex string.

    Conventions:
      %...%    wrapper  -> %[^%\n]+%
      <<...>>  wrapper  -> <<[^>\n]+>>
      ~...~    wrapper  -> ~[^~\n]+~
      $...     prefix   -> (?<![A-Za-z0-9_])\\$[A-Za-z_][A-Za-z0-9_]*
      !...!    wrapper  -> ![^!\n]+!
      {…}      wrapper  -> \\{[^}\n]+\\}
      (...)    raw regex — used as-is (strip outer parens)
    """
    p = pattern_str.strip()
    if not p:
        return None
    if p.startswith("(") and p.endswith(")"):
        return p[1:-1]
    if "..." in p:
        parts = p.split("...")
        if len(parts) == 2:
            left, right = parts
            if right:
                # wrapper: escape delimiters, match content
                first_close = right[0]
                content = "[^" + re.escape(first_close) + "\n]+"
                return re.escape(left) + content + re.escape(right)
            else:
                # prefix: left + word identifier
                boundary = "(?<![A-Za-z0-9_])" if not re.match(r"\w", left[-1]) else "\\b"
                return boundary + re.escape(left) + "[A-Za-z_][A-Za-z0-9_]*"
    return re.escape(p)


def _variable_patterns(lang_def):
    """Return list of compiled regex patterns from lang_def["variable_patterns"]."""
    result = []
    if not isinstance(lang_def, dict):
        return result
    raw_list = lang_def.get("variable_patterns", [])
    if not isinstance(raw_list, list):
        return result
    seen = set()
    for entry in raw_list:
        pat_str = _variable_pattern_to_regex(str(entry).strip())
        if pat_str and pat_str not in seen:
            seen.add(pat_str)
            try:
                result.append(re.compile(pat_str))
            except re.error:
                pass
    return result


def _path_pattern(lang_def):
    """Return regex string for path detection.
    Key absent → no detection.  Key present + empty → no detection.
    Key present + valid regex → use it.
    """
    if not isinstance(lang_def, dict):
        return None
    pat = lang_def.get("path_pattern", None)
    if pat is None:
        return None  # Key absent — no path detection
    pat = str(pat).strip()
    if pat:
        try:
            re.compile(pat)
            return pat
        except re.error:
            return None
    return None  # explicitly empty = disabled

# ---------------------------------------------------------------------------
# Shared priority-aware segment painter
# ---------------------------------------------------------------------------

def _paint_seg(segments, start, end, fmt_or_style, priority):
    """
    Paint [start, end) at *priority*.
    Existing segments with priority >= incoming keep their value.
    Works for both (fmt, priority) tuples (BasicHighlighter) and
    (style_int, priority) tuples (TuflowLexer) — the caller decides the type.
    """
    out = []
    for a, b, f, p in segments:
        if end <= a or start >= b:
            out.append((a, b, f, p))
            continue
        if a < start:
            out.append((a, start, f, p))
        ov_s = max(a, start)
        ov_e = min(b, end)
        if p >= priority:
            out.append((ov_s, ov_e, f, p))
        else:
            out.append((ov_s, ov_e, fmt_or_style, priority))
        if end < b:
            out.append((end, b, f, p))
    return out


# ---------------------------------------------------------------------------
# Plain-text QSyntaxHighlighter
# ---------------------------------------------------------------------------

class BasicHighlighter(QSyntaxHighlighter):

    def __init__(self, document, language_key, config):
        super().__init__(document)
        self._language_key = language_key
        self._config       = config
        self._build_formats()

    # Style key → tab key mapping for override mode lookup
    _STYLE_TO_TAB = {
        "comment": "comments",
        "keyword1": "keywords", "keyword2": "keywords", "keyword3": "keywords",
        "keyword4": "keywords", "keyword5": "keywords", "keyword6": "keywords",
        "number": "numbers",
        "string": "delimiters",
        "operator": "operators",
        "path": "path",
        "variable": "variables",
        "text": "general", "folding": "folding",
    }

    def _build_formats(self):
        config   = self._config
        lang_key = self._language_key
        lang_def = _lang_def(config, lang_key)
        active_theme  = get_theme(config["theme"])
        factory_theme = get_factory_theme(config["theme"])
        overrides = lang_def.get("_tab_overrides", {})
        # Config with factory font for Mode 0
        factory_config = dict(config)
        factory_config["font_family"] = factory_theme.get("font_family", config.get("font_family", "Consolas"))
        factory_config["font_size"] = factory_theme.get("font_size", config.get("font_size", 10))
        # Build a lang_def without T3 styles for Mode 0/1
        lang_def_no_styles = dict(lang_def)
        lang_def_no_styles.pop("styles", None)
        self.formats = {}
        for name in ALL_STYLE_KEYS:
            tab_key = self._STYLE_TO_TAB.get(name, "general")
            mode = overrides.get(tab_key, 1)
            if isinstance(mode, bool):
                mode = 2 if mode else 1
            theme = factory_theme if mode == 0 else active_theme
            cfg = factory_config if mode == 0 else config
            # Mode 0/1: ignore T3 styles. Mode 2: use T3 styles.
            ld = lang_def if mode == 2 else lang_def_no_styles
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(style_color(theme, ld, name)))
            fmt.setBackground(QColor(style_paper(theme, ld, name)))
            fmt.setFont(style_font(theme, cfg, ld, name))
            self.formats[name] = fmt
        # ── Cache PRE-COMPILED patterns (rebuilt only on apply_config) ──
        self._c_base = lang_def.get("base", lang_key)
        self._c_flags = _case_flags(lang_def)
        self._c_priorities = _priorities(config, lang_def)
        _f = self._c_flags
        op_tokens = _operator_tokens(lang_def, self._c_base)
        self._c_op_re = re.compile("|".join(re.escape(t) for t in op_tokens), _f) if op_tokens else None
        np = _number_pattern(lang_def)
        self._c_num_re = re.compile(np, _f) if np else None
        self._c_delim_res = [re.compile(p, _f | re.DOTALL) for p in _delimiter_patterns(lang_def)]
        self._c_var_res = [vp for vp in _variable_patterns(lang_def)]  # already compiled
        pp = _path_pattern(lang_def)
        self._c_path_re = re.compile(pp, _f) if pp else None
        self._c_comment_res = [re.compile(p, _f | re.MULTILINE) for p in _comment_patterns(lang_def, self._c_base)]
        grp_styles = _group_styles(lang_def)
        prefix_modes = lang_def.get("prefix_modes", [False] * 6) if isinstance(lang_def, dict) else [False] * 6
        self._c_kw_res = []
        for idx, grp_text in enumerate(_keyword_groups(lang_def)):
            style_key = grp_styles[idx]
            pm = bool(prefix_modes[idx]) if idx < len(prefix_modes) else False
            kw_patterns = []
            for kw in _tokens_from_group(grp_text):
                kw_patterns.append(_keyword_pattern(kw, pm))
            if kw_patterns:
                kw_patterns.sort(key=len, reverse=True)
                combined = "|".join(kw_patterns)
                try:
                    self._c_kw_res.append((re.compile(combined, _f), style_key, idx))
                except re.error:
                    pass
        fold = lang_def.get("folding", {}) if isinstance(lang_def, dict) else {}
        self._c_fold_res = []
        for prefix in ("comment", "code1", "code2", "code3", "code4", "code5"):
            for suffix in ("_open", "_middle", "_close"):
                v = str(fold.get(prefix + suffix, "")).strip() if isinstance(fold, dict) else ""
                if v:
                    try:
                        self._c_fold_res.append(re.compile("^\\s*" + re.escape(v) + "\\b", _f | re.MULTILINE))
                    except re.error:
                        pass

    def highlightBlock(self, text):
        if not text:
            return
        f     = self.formats
        p     = self._c_priorities
        base  = self._c_base
        n     = len(text)

        # Character array approach
        fmt_arr = [None] * n  # format per character
        pri_arr = bytearray(n)  # priority per character (bytearray for speed)

        def apply_re(compiled_re, fmt, priority):
            for m in compiled_re.finditer(text):
                s, e = m.start(), m.end()
                chunk = pri_arr[s:e]
                if max(chunk) < priority:
                    for i in range(s, e):
                        fmt_arr[i] = fmt
                    pri_arr[s:e] = bytes([priority]) * (e - s)
                else:
                    for i in range(s, e):
                        if priority > pri_arr[i]:
                            fmt_arr[i] = fmt
                            pri_arr[i] = priority

        def paint(pattern_str, fmt, priority, extra_flags=0):
            try:
                for m in re.finditer(pattern_str, text, self._c_flags | extra_flags):
                    s, e = m.start(), m.end()
                    chunk = pri_arr[s:e]
                    if max(chunk) < priority:
                        for i in range(s, e):
                            fmt_arr[i] = fmt
                        pri_arr[s:e] = bytes([priority]) * (e - s)
                    else:
                        for i in range(s, e):
                            if priority > pri_arr[i]:
                                fmt_arr[i] = fmt
                                pri_arr[i] = priority
            except re.error:
                pass

        if self._c_op_re:
            apply_re(self._c_op_re, f["operator"], p["operator"])
        if self._c_num_re:
            apply_re(self._c_num_re, f["number"], p["number"])
        for rx in self._c_delim_res:
            apply_re(rx, f["string"], p["string"])
        if "variable" in f:
            var_pri = p.get("variable", p.get("path", 15) + 1)
            for rx in self._c_var_res:
                apply_re(rx, f["variable"], var_pri)

        if base == "batch":
            paint(r"%[^%]+%|![^!]+!", f.get("keyword1", f["text"]), p["keyword1"])
        elif base == "python":
            paint(r"@[A-Za-z_][A-Za-z0-9_.]*", f.get("keyword3", f.get("keyword1", f["text"])), p["keyword3"])
            paint(r'"""[^"]*"""|\'\'\'[^\']*\'\'\'', f["string"], p["string"])
            paint(r'\b[fFrRbBuU]{1,2}(?=["\'])', f.get("keyword2", f["string"]), p["keyword2"])
        elif base == "r":
            paint(r"<<-|->>|<-|->", f["operator"], p["operator"])
            paint(r"%[A-Za-z><!*+/|&.]+%", f["operator"], p["operator"])
            paint(r"\$[A-Za-z_.][A-Za-z0-9_.]*", f.get("variable", f.get("keyword3", f["text"])), p.get("variable", p.get("keyword3", 8)))
            paint(r"`[^`\n]+`", f.get("variable", f["string"]), p.get("variable", p["string"]))
            paint(r"~", f["operator"], p["operator"])
        elif base == "sql":
            paint(r"--.*$", f["comment"], p["comment"], re.MULTILINE)
            paint(r"\[[^\]\n]+\]", f.get("variable", f["string"]), p.get("variable", p["string"]))
            paint(r"`[^`\n]+`", f.get("variable", f["string"]), p.get("variable", p["string"]))
            paint(r"\b\d+(?:\.\d+)?\b", f["number"], p["number"])
        elif base == "html":
            paint(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>", f.get("keyword1", f["text"]), p["keyword1"])
            paint(r"<!--.*?-->", f["comment"], p["comment"])
            paint(r'\b[A-Za-z_-]+(?=\s*=)', f.get("keyword2", f["text"]), p["keyword2"])
            paint(r'=\s*"[^"]*"|=\s*\'[^\']*\'', f["string"], p["string"])
            paint(r"&[A-Za-z]+;|&#\d+;|&#x[0-9A-Fa-f]+;", f.get("keyword3", f["number"]), p["keyword3"])

        _KW_PRIORITIES = [p["keyword1"], p["keyword2"], p["keyword3"], p["keyword4"], p["keyword5"], p["keyword6"]]
        for kw_re, style_key, idx in self._c_kw_res:
            apply_re(kw_re, f.get(style_key, f.get("keyword1", f["text"])), _KW_PRIORITIES[idx])

        if self._c_path_re:
            apply_re(self._c_path_re, f["path"], p["path"])
        if "folding" in f:
            for rx in self._c_fold_res:
                apply_re(rx, f["folding"], p["path"] - 1)
        for rx in self._c_comment_res:
            apply_re(rx, f["comment"], p["comment"])

        # Flush to Qt — run-length encode the format array
        i = 0
        while i < n:
            fmt = fmt_arr[i]
            j = i + 1
            while j < n and fmt_arr[j] is fmt:
                j += 1
            if fmt is not None:
                self.setFormat(i, j - i, fmt)
            i = j


# ---------------------------------------------------------------------------
# QScintilla custom lexer
# ---------------------------------------------------------------------------
if TRY_QSCI:
    class TuflowLexer(QsciLexerCustom):
        DEFAULT  = 0
        COMMENT  = 1
        FOLDING  = 2
        KEYWORD1 = 3
        KEYWORD2 = 4
        KEYWORD3 = 5
        KEYWORD4 = 6
        KEYWORD5 = 7
        KEYWORD6 = 8
        NUMBER   = 9
        STRING   = 10
        OPERATOR = 11
        PATH     = 12
        VARIABLE = 13

        _STYLE_MAP = {
            0: "text",      1: "comment",   2: "folding",
            3: "keyword1",  4: "keyword2",  5: "keyword3",
            6: "keyword4",  7: "keyword5",  8: "keyword6",
            9: "number",    10: "string",   11: "operator", 12: "path",
            13: "variable",
        }
        _KW_STYLE_LOOKUP = {
            "keyword1": 3, "keyword2": 4, "keyword3": 5,
            "keyword4": 6, "keyword5": 7, "keyword6": 8,
        }

        def __init__(self, parent=None, language_key="tuflow", config=None):
            super().__init__(parent)
            from .qfat04_config import load_config
            self.config   = config or load_config()
            self.lang_key = language_key
            lang_def      = _lang_def(self.config, language_key)
            self._base    = lang_def.get("base", language_key)
            self._set_fonts()

        def language(self):
            return "QFAT04"

        def defaultFoldingBits(self, style):
            return 2   # enable folding for this lexer

        def foldingMarkers(self, style):
            return 2

        def description(self, style):
            return self._STYLE_MAP.get(style, "Default")

        def _set_fonts(self):
            active_theme  = get_theme(self.config["theme"])
            factory_theme = get_factory_theme(self.config["theme"])
            lang_def = _lang_def(self.config, self.lang_key)
            overrides = lang_def.get("_tab_overrides", {})
            _STYLE_TO_TAB = {
                "comment": "comments",
                "keyword1": "keywords", "keyword2": "keywords", "keyword3": "keywords",
                "keyword4": "keywords", "keyword5": "keywords", "keyword6": "keywords",
                "number": "numbers",
                "string": "delimiters",
                "operator": "operators",
                "path": "path",
                "variable": "variables",
                "text": "general", "folding": "folding",
            }
            # Config with factory font for Mode 0
            factory_config = dict(self.config)
            factory_config["font_family"] = factory_theme.get("font_family", self.config.get("font_family", "Consolas"))
            factory_config["font_size"] = factory_theme.get("font_size", self.config.get("font_size", 10))
            # Build a lang_def without T3 styles for Mode 0/1
            lang_def_no_styles = dict(lang_def)
            lang_def_no_styles.pop("styles", None)
            self.setDefaultFont(style_font(active_theme, self.config, lang_def, "text"))
            self.setDefaultPaper(QColor(style_paper(active_theme, lang_def, "text")))
            for i, sk in self._STYLE_MAP.items():
                tab_key = _STYLE_TO_TAB.get(sk, "general")
                mode = overrides.get(tab_key, 1)
                if isinstance(mode, bool):
                    mode = 2 if mode else 1
                theme = factory_theme if mode == 0 else active_theme
                cfg = factory_config if mode == 0 else self.config
                ld = lang_def if mode == 2 else lang_def_no_styles
                self.setColor(QColor(style_color(theme, ld, sk)), i)
                self.setFont(style_font(theme, cfg, ld, sk), i)
                self.setPaper(QColor(style_paper(theme, ld, sk)), i)
            # ── Cache PRE-COMPILED patterns for _classify ─────────────
            self._c_lang_def = lang_def
            self._c_base = lang_def.get("base", self.lang_key) if isinstance(lang_def, dict) else self.lang_key
            self._c_flags = _case_flags(lang_def)
            self._c_priorities = _priorities(self.config, lang_def)
            _f = self._c_flags
            op_tokens = _operator_tokens(lang_def, self._c_base)
            self._c_op_re = re.compile("|".join(re.escape(t) for t in op_tokens), _f) if op_tokens else None
            np = _number_pattern(lang_def)
            self._c_num_re = re.compile(np, _f) if np else None
            self._c_delim_res = [re.compile(p, _f | re.DOTALL) for p in _delimiter_patterns(lang_def)]
            self._c_var_res = [vp for vp in _variable_patterns(lang_def)]  # already compiled
            pp = _path_pattern(lang_def)
            self._c_path_re = re.compile(pp, _f) if pp else None
            self._c_comment_res = [re.compile(p, _f | re.MULTILINE) for p in _comment_patterns(lang_def, self._c_base)]
            grp_styles = _group_styles(lang_def)
            prefix_modes = lang_def.get("prefix_modes", [False] * 6) if isinstance(lang_def, dict) else [False] * 6
            self._c_kw_res = []  # list of (compiled_re, style_int, group_idx)
            for idx, grp_text in enumerate(_keyword_groups(lang_def)):
                style_key = grp_styles[idx]
                pm = bool(prefix_modes[idx]) if idx < len(prefix_modes) else False
                kw_style = self._KW_STYLE_LOOKUP.get(style_key, self.KEYWORD1)
                kw_patterns = []
                for kw in _tokens_from_group(grp_text):
                    kw_patterns.append(_keyword_pattern(kw, pm))
                if kw_patterns:
                    kw_patterns.sort(key=len, reverse=True)
                    combined = "|".join(kw_patterns)
                    try:
                        self._c_kw_res.append((re.compile(combined, _f), kw_style, idx))
                    except re.error:
                        pass
            fold = lang_def.get("folding", {}) if isinstance(lang_def, dict) else {}
            self._c_fold_res = []
            for prefix in ("comment", "code1", "code2", "code3", "code4", "code5"):
                for suffix in ("_open", "_middle", "_close"):
                    v = str(fold.get(prefix + suffix, "")).strip() if isinstance(fold, dict) else ""
                    if v:
                        try:
                            self._c_fold_res.append(re.compile("^\\s*" + re.escape(v) + "\\b", _f | re.MULTILINE))
                        except re.error:
                            pass

        def styleText(self, start, end):
            editor = self.editor()
            if editor is None:
                return
            start_line = editor.SendScintilla(editor.SCI_LINEFROMPOSITION, start)
            end_line = editor.SendScintilla(editor.SCI_LINEFROMPOSITION, end)
            total_lines = end_line - start_line + 1

            # Only style visible lines + buffer for large files
            if total_lines > 100:
                first_vis = editor.SendScintilla(editor.SCI_GETFIRSTVISIBLELINE)
                lines_on_screen = editor.SendScintilla(editor.SCI_LINESONSCREEN)
                buf = 20  # extra lines above/below
                vis_start = max(start_line, first_vis - buf)
                vis_end = min(end_line, first_vis + lines_on_screen + buf)
                # Mark everything as default first
                self.startStyling(start)
                self.setStyling(end - start, self.DEFAULT)
                # Then style only visible range
                if vis_start <= vis_end:
                    self._style_block(editor, vis_start, vis_end)
                # Set up scroll watcher if not already
                if not hasattr(self, '_scroll_connected'):
                    self._scroll_connected = True
                    try:
                        editor.SCN_UPDATEUI = 2039
                        editor.SendScintilla(editor.SCI_SETMODEVENTMASK,
                            editor.SendScintilla(0x2091) | 0x3)  # SC_MOD_CHANGESTYLE | SC_UPDATE_V_SCROLL
                    except Exception:
                        pass
                    # Use a timer to restyle on scroll
                    from qgis.PyQt.QtCore import QTimer
                    self._scroll_timer = QTimer()
                    self._scroll_timer.setSingleShot(True)
                    self._scroll_timer.timeout.connect(self._restyle_visible)
                    self._scroll_timer.start(100)
                    # Connect vertical scrollbar
                    try:
                        vbar = editor.verticalScrollBar()
                        if vbar:
                            vbar.valueChanged.connect(self._on_scroll)
                    except Exception:
                        pass
                self._set_fold_levels(editor, start, end)
            else:
                # Small range — style everything
                self._style_block(editor, start_line, end_line)
                self._set_fold_levels(editor, start, end)

        def _on_scroll(self, _value=None):
            """Scroll event — debounce and restyle visible."""
            if hasattr(self, '_scroll_timer'):
                self._scroll_timer.start(50)  # 50ms debounce

        def _restyle_visible(self):
            """Restyle currently visible lines."""
            editor = self.editor()
            if editor is None:
                return
            first_vis = editor.SendScintilla(editor.SCI_GETFIRSTVISIBLELINE)
            lines_on_screen = editor.SendScintilla(editor.SCI_LINESONSCREEN)
            total = editor.SendScintilla(editor.SCI_GETLINECOUNT)
            buf = 20
            vis_start = max(0, first_vis - buf)
            vis_end = min(total - 1, first_vis + lines_on_screen + buf)
            if vis_start <= vis_end:
                self._style_block(editor, vis_start, vis_end)

        def _style_block(self, editor, start_line, end_line):
            """Style a range of lines as one block — single regex pass."""
            lines_text = []
            line_lengths = []
            eol_extras = []
            for i in range(start_line, end_line + 1):
                lt = editor.text(i)
                lines_text.append(lt)
                line_lengths.append(len(lt))
                sci_len = editor.SendScintilla(editor.SCI_LINELENGTH, i)
                eol_extras.append(sci_len - len(lt))
            text = "".join(lines_text)
            n = len(text)

            # Classify with bytearray
            styles = bytearray(n)
            priorities = bytearray(n)
            p = self._c_priorities
            base = self._c_base

            def apply_re(compiled_re, style, priority):
                pri_byte = priority
                for m in compiled_re.finditer(text):
                    s, e = m.start(), m.end()
                    # Check if any char in range has higher priority
                    chunk = priorities[s:e]
                    if max(chunk) < pri_byte:
                        # Fast path: entire range can be overwritten
                        styles[s:e] = bytes([style]) * (e - s)
                        priorities[s:e] = bytes([pri_byte]) * (e - s)
                    else:
                        # Slow path: check per char
                        for i in range(s, e):
                            if pri_byte > priorities[i]:
                                styles[i] = style
                                priorities[i] = pri_byte

            def apply_pat(pattern, style, priority, extra_flags=0):
                pri_byte = priority
                try:
                    for m in re.finditer(pattern, text, self._c_flags | extra_flags):
                        s, e = m.start(), m.end()
                        chunk = priorities[s:e]
                        if max(chunk) < pri_byte:
                            styles[s:e] = bytes([style]) * (e - s)
                            priorities[s:e] = bytes([pri_byte]) * (e - s)
                        else:
                            for i in range(s, e):
                                if pri_byte > priorities[i]:
                                    styles[i] = style
                                    priorities[i] = pri_byte
                except re.error:
                    pass

            if self._c_op_re:
                apply_re(self._c_op_re, self.OPERATOR, p["operator"])
            if self._c_num_re:
                apply_re(self._c_num_re, self.NUMBER, p["number"])
            for rx in self._c_delim_res:
                apply_re(rx, self.STRING, p["string"])
            var_pri = p.get("variable", p.get("path", 15) + 1)
            for rx in self._c_var_res:
                apply_re(rx, self.VARIABLE, var_pri)
            if base == "batch":
                apply_pat(r"%[^%]+%|![^!]+!", self.KEYWORD1, p["keyword1"])
            elif base == "python":
                apply_pat(r"@[A-Za-z_][A-Za-z0-9_.]*", self._KW_STYLE_LOOKUP.get("keyword3", self.KEYWORD1), p["keyword3"])
                apply_pat(r'"""[^"]*"""|\'\'\'[^\']*\'\'\'', self.STRING, p["string"])
                apply_pat(r'\b[fFrRbBuU]{1,2}(?=["\'])', self._KW_STYLE_LOOKUP.get("keyword2", self.KEYWORD2), p["keyword2"])
            elif base == "r":
                for pat, sty, pri in [(r"<<-|->>|<-|->", self.OPERATOR, p["operator"]),
                                      (r"%[A-Za-z><!*+/|&.]+%", self.OPERATOR, p["operator"]),
                                      (r"\$[A-Za-z_.][A-Za-z0-9_.]*", self.VARIABLE, p.get("variable", 8)),
                                      (r"`[^`\n]+`", self.VARIABLE, p.get("variable", p["string"])),
                                      (r"~", self.OPERATOR, p["operator"])]:
                    apply_pat(pat, sty, pri)
            elif base == "sql":
                apply_pat(r"--.*$", self.COMMENT, p["comment"], re.MULTILINE)
                apply_pat(r"\[[^\]\n]+\]", self.VARIABLE, p.get("variable", p["string"]))
                apply_pat(r"`[^`\n]+`", self.VARIABLE, p.get("variable", p["string"]))
            elif base == "html":
                for pat, sty, pri in [(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>", self.KEYWORD1, p["keyword1"]),
                                      (r"<!--.*?-->", self.COMMENT, p["comment"]),
                                      (r'\b[A-Za-z_-]+(?=\s*=)', self.KEYWORD2, p["keyword2"]),
                                      (r'=\s*"[^"]*"|=\s*\'[^\']*\'', self.STRING, p["string"]),
                                      (r"&[A-Za-z]+;|&#\d+;|&#x[0-9A-Fa-f]+;", self._KW_STYLE_LOOKUP.get("keyword3", self.KEYWORD1), p["keyword3"])]:
                    apply_pat(pat, sty, pri)
            _KW_PRI = [p["keyword1"], p["keyword2"], p["keyword3"], p["keyword4"], p["keyword5"], p["keyword6"]]
            for kw_re, kw_style, idx in self._c_kw_res:
                apply_re(kw_re, kw_style, _KW_PRI[idx])
            if self._c_path_re:
                apply_re(self._c_path_re, self.PATH, p["path"])
            for rx in self._c_fold_res:
                apply_re(rx, self.FOLDING, p["path"] - 1)
            for rx in self._c_comment_res:
                apply_re(rx, self.COMMENT, p["comment"])

            # Apply styles line-by-line with EOL correction
            line_start = editor.SendScintilla(editor.SCI_POSITIONFROMLINE, start_line)
            self.startStyling(line_start)
            offset = 0
            for li in range(end_line - start_line + 1):
                llen = line_lengths[li]
                i = 0
                while i < llen:
                    sty = styles[offset + i]
                    j = i + 1
                    while j < llen and styles[offset + j] == sty:
                        j += 1
                    self.setStyling(j - i, sty)
                    i = j
                if eol_extras[li] > 0:
                    self.setStyling(eol_extras[li], self.DEFAULT)
                offset += llen

        def _style_deferred_batch(self):
            """Style next chunk of deferred lines."""
            editor = self.editor()
            if editor is None or not hasattr(self, '_deferred_ranges') or not self._deferred_ranges:
                return
            rng_start, rng_end = self._deferred_ranges[0]
            BATCH = 200
            batch_end = min(rng_start + BATCH - 1, rng_end)
            try:
                self._style_block(editor, rng_start, batch_end)
            except Exception:
                self._deferred_ranges.clear()
                return
            if batch_end >= rng_end:
                self._deferred_ranges.pop(0)
            else:
                self._deferred_ranges[0] = (batch_end + 1, rng_end)
            if self._deferred_ranges:
                self._defer_timer.start(15)
            else:
                try:
                    self._set_fold_levels(editor, self._deferred_doc_start, self._deferred_doc_end)
                except Exception:
                    pass

        def _fold_patterns(self):
            """
            Return (open_patterns, close_patterns) compiled regex lists.
            Reads from lang_def["folding"] with sensible TUFLOW defaults.
            """
            lang_def = getattr(self, '_c_lang_def', None) or _lang_def(self.config, self.lang_key)
            base     = getattr(self, '_c_base', self._base)
            flags    = re.IGNORECASE

            fold = lang_def.get("folding", {}) if isinstance(lang_def, dict) else {}

            # Collect open/close/middle tokens from the language definition
            opens   = []
            closes  = []
            seen_open  = set()
            seen_close = set()

            for key in ("comment_open", "code1_open", "code2_open", "code3_open", "code4_open", "code5_open"):
                v = str(fold.get(key, "")).strip() if isinstance(fold, dict) else ""
                if v and v not in seen_open:
                    seen_open.add(v)
                    try: opens.append(re.compile("^\\s*" + re.escape(v) + "\\b", flags))
                    except re.error: pass

            for key in ("comment_close", "code1_close", "code2_close", "code3_close", "code4_close", "code5_close"):
                v = str(fold.get(key, "")).strip() if isinstance(fold, dict) else ""
                if v and v not in seen_close:
                    seen_close.add(v)
                    try: closes.append(re.compile("^\\s*" + re.escape(v) + "\\b", flags))
                    except re.error: pass

            # Built-in TUFLOW defaults if nothing defined
            if base == "tuflow" and not opens:
                default_opens  = [
                    "^\\s*if\\s+scenario\\b", "^\\s*if\\s+event\\b",
                    "^\\s*start\\s+2d\\s+domain\\b",
                    "^\\s*start\\s+1d\\s+domain\\b",
                ]
                default_closes = [
                    "^\\s*end\\s+if\\b",
                    "^\\s*end\\s+2d\\s+domain\\b",
                    "^\\s*end\\s+1d\\s+domain\\b",
                ]
                for pat in default_opens:
                    try: opens.append(re.compile(pat, flags))
                    except re.error: pass
                for pat in default_closes:
                    try: closes.append(re.compile(pat, flags))
                    except re.error: pass

            return opens, closes

        def _set_fold_levels(self, editor, start, end):
            """Walk ALL lines and set SCI_SETFOLDLEVEL on each.
            Must process the full document to get nesting right.
            Only runs when styleText covers position 0 to avoid redundant passes."""
            if start > 0:
                return
            SC_FOLDLEVELBASE       = 0x400
            SC_FOLDLEVELHEADERFLAG = 0x2000

            lang_def = _lang_def(self.config, self.lang_key)
            base = lang_def.get("base", "text") if isinstance(lang_def, dict) else "text"

            # Python uses indentation-based folding
            if base == "python":
                self._set_fold_levels_python(editor, SC_FOLDLEVELBASE, SC_FOLDLEVELHEADERFLAG)
                return

            opens, closes = self._fold_patterns()

            # Language settings
            fold_data = lang_def.get("folding", {}) if isinstance(lang_def, dict) else {}
            compact = bool(fold_data.get("compact", False)) if isinstance(fold_data, dict) else False

            # Comment folding: detect runs of consecutive comment lines
            fold_comments = bool(lang_def.get("fold_comments", False)) if isinstance(lang_def, dict) else False
            comment_prefixes = []
            if fold_comments:
                cp = lang_def.get("comment_prefixes", []) if isinstance(lang_def, dict) else []
                comment_prefixes = [str(x).strip() for x in cp if str(x).strip()]

            if not opens and not fold_comments:
                return

            total_lines = editor.lines()
            level = 0

            def _comment_prefix_at_start(line_text):
                """Return the comment prefix if line starts with it, else None."""
                stripped = line_text.lstrip()
                for cp in comment_prefixes:
                    if stripped.startswith(cp):
                        return cp
                return None

            # Pre-scan for comment runs
            comment_run_start = {}
            comment_run_end = {}
            if fold_comments and comment_prefixes:
                i = 0
                while i < total_lines:
                    line_text = editor.text(i)
                    cp = _comment_prefix_at_start(line_text)
                    if cp is not None:
                        run_start = i
                        run_prefix = cp
                        j = i + 1
                        while j < total_lines:
                            next_line = editor.text(j)
                            ncp = _comment_prefix_at_start(next_line)
                            if ncp == run_prefix:
                                j += 1
                            else:
                                break
                        run_end = j - 1
                        if run_end > run_start:
                            comment_run_start[run_start] = True
                            comment_run_end[run_end] = True
                        i = j
                    else:
                        i += 1

            for lineno in range(total_lines):
                line_text = editor.text(lineno)
                is_open  = any(p.match(line_text) for p in opens) if opens else False
                is_close = any(p.match(line_text) for p in closes) if closes else False
                is_comment_start = lineno in comment_run_start
                is_comment_end   = lineno in comment_run_end
                is_blank = not line_text.strip()

                if is_close or is_comment_end:
                    if is_close:
                        level = max(0, level - 1)
                    if is_comment_end and not is_close:
                        level = max(0, level - 1)

                fold_level = SC_FOLDLEVELBASE + level
                if is_open or is_comment_start:
                    fold_level |= SC_FOLDLEVELHEADERFLAG

                # Compact folding: blank lines inside a fold block stay at the
                # parent level so they collapse with the block above them.
                # Without compact, blank lines after End If stay visible.
                if compact and is_blank and level > 0:
                    fold_level = SC_FOLDLEVELBASE + level

                editor.SendScintilla(editor.SCI_SETFOLDLEVEL, lineno, fold_level)

                if is_open or is_comment_start:
                    level += 1

        def _set_fold_levels_python(self, editor, SC_FOLDLEVELBASE, SC_FOLDLEVELHEADERFLAG):
            """Indentation-based folding for Python.
            A line that is followed by a more-indented line is a fold header."""
            total_lines = editor.lines()
            if total_lines == 0:
                return

            # Pre-compute indent levels (number of leading spaces, tabs=4)
            indents = []
            is_blank = []
            for i in range(total_lines):
                line = editor.text(i)
                stripped = line.lstrip()
                if not stripped or stripped.startswith("#"):
                    indents.append(-1)  # blank or comment-only
                    is_blank.append(True)
                else:
                    indent = 0
                    for ch in line:
                        if ch == " ": indent += 1
                        elif ch == "\t": indent += 4
                        else: break
                    indents.append(indent)
                    is_blank.append(False)

            for i in range(total_lines):
                if is_blank[i]:
                    # Blank/comment lines: use the indent of the next non-blank line
                    effective = 0
                    for j in range(i + 1, total_lines):
                        if not is_blank[j]:
                            effective = indents[j]
                            break
                    level = effective // 4
                    editor.SendScintilla(editor.SCI_SETFOLDLEVEL, i,
                                         SC_FOLDLEVELBASE + level)
                else:
                    level = indents[i] // 4
                    # Check if next non-blank line has higher indent = fold header
                    next_indent = -1
                    for j in range(i + 1, total_lines):
                        if not is_blank[j]:
                            next_indent = indents[j]
                            break
                    fold_level = SC_FOLDLEVELBASE + level
                    if next_indent > indents[i]:
                        fold_level |= SC_FOLDLEVELHEADERFLAG
                    editor.SendScintilla(editor.SCI_SETFOLDLEVEL, i, fold_level)

        def _classify(self, text):
            """Fast line classifier using bytearray."""
            n = len(text)
            if n == 0:
                return [(0, self.DEFAULT)]
            styles = bytearray([self.DEFAULT]) * n
            priorities = bytearray(n)
            base = self._c_base
            p = self._c_priorities

            def apply_re(compiled_re, style, priority):
                for m in compiled_re.finditer(text):
                    s, e = m.start(), m.end()
                    if max(priorities[s:e]) < priority:
                        styles[s:e] = bytes([style]) * (e - s)
                        priorities[s:e] = bytes([priority]) * (e - s)
                    else:
                        for i in range(s, e):
                            if priority > priorities[i]:
                                styles[i] = style
                                priorities[i] = priority

            def apply_pat(pattern, style, priority, extra_flags=0):
                try:
                    for m in re.finditer(pattern, text, self._c_flags | extra_flags):
                        s, e = m.start(), m.end()
                        if max(priorities[s:e]) < priority:
                            styles[s:e] = bytes([style]) * (e - s)
                            priorities[s:e] = bytes([priority]) * (e - s)
                        else:
                            for i in range(s, e):
                                if priority > priorities[i]:
                                    styles[i] = style
                                    priorities[i] = priority
                except re.error:
                    pass

            # Apply in priority order (lowest first, highest last wins)
            if self._c_op_re:
                apply_re(self._c_op_re, self.OPERATOR, p["operator"])
            if self._c_num_re:
                apply_re(self._c_num_re, self.NUMBER, p["number"])
            for rx in self._c_delim_res:
                apply_re(rx, self.STRING, p["string"])
            var_pri = p.get("variable", p.get("path", 15) + 1)
            for rx in self._c_var_res:
                apply_re(rx, self.VARIABLE, var_pri)

            if base == "batch":
                apply_pat(r"%[^%]+%|![^!]+!", self.KEYWORD1, p["keyword1"])
            elif base == "python":
                apply_pat(r"@[A-Za-z_][A-Za-z0-9_.]*", self._KW_STYLE_LOOKUP.get("keyword3", self.KEYWORD1), p["keyword3"])
                apply_pat(r'"""[^"]*"""|\'\'\'[^\']*\'\'\'', self.STRING, p["string"])
                apply_pat(r'\b[fFrRbBuU]{1,2}(?=["\'])', self._KW_STYLE_LOOKUP.get("keyword2", self.KEYWORD2), p["keyword2"])
            elif base == "r":
                for pat, sty, pri in [(r"<<-|->>|<-|->", self.OPERATOR, p["operator"]),
                                      (r"%[A-Za-z><!*+/|&.]+%", self.OPERATOR, p["operator"]),
                                      (r"\$[A-Za-z_.][A-Za-z0-9_.]*", self.VARIABLE, p.get("variable", 8)),
                                      (r"`[^`\n]+`", self.VARIABLE, p.get("variable", p["string"])),
                                      (r"~", self.OPERATOR, p["operator"])]:
                    apply_pat(pat, sty, pri)
            elif base == "sql":
                apply_pat(r"--.*$", self.COMMENT, p["comment"], re.MULTILINE)
                apply_pat(r"\[[^\]\n]+\]", self.VARIABLE, p.get("variable", p["string"]))
                apply_pat(r"`[^`\n]+`", self.VARIABLE, p.get("variable", p["string"]))
            elif base == "html":
                for pat, sty, pri in [(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>", self.KEYWORD1, p["keyword1"]),
                                      (r"<!--.*?-->", self.COMMENT, p["comment"]),
                                      (r'\b[A-Za-z_-]+(?=\s*=)', self.KEYWORD2, p["keyword2"]),
                                      (r'=\s*"[^"]*"|=\s*\'[^\']*\'', self.STRING, p["string"]),
                                      (r"&[A-Za-z]+;|&#\d+;|&#x[0-9A-Fa-f]+;", self._KW_STYLE_LOOKUP.get("keyword3", self.KEYWORD1), p["keyword3"])]:
                    apply_pat(pat, sty, pri)

            _KW_PRIORITIES = [p["keyword1"], p["keyword2"], p["keyword3"], p["keyword4"], p["keyword5"], p["keyword6"]]
            for kw_re, kw_style, idx in self._c_kw_res:
                apply_re(kw_re, kw_style, _KW_PRIORITIES[idx])

            if self._c_path_re:
                apply_re(self._c_path_re, self.PATH, p["path"])
            for rx in self._c_fold_res:
                apply_re(rx, self.FOLDING, p["path"] - 1)
            for rx in self._c_comment_res:
                apply_re(rx, self.COMMENT, p["comment"])

            # Convert char array to run-length encoded segments
            result = []
            if n > 0:
                cur_style = styles[0]
                cur_len = 1
                for i in range(1, n):
                    if styles[i] == cur_style:
                        cur_len += 1
                    else:
                        result.append((cur_len, cur_style))
                        cur_style = styles[i]
                        cur_len = 1
                result.append((cur_len, cur_style))
            return result

        @staticmethod
        def _paint(segments, start, end, style, priority):
            # Kept for API compatibility; delegates to shared helper
            return _paint_seg(segments, start, end, style, priority)

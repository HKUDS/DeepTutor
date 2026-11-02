"""Small runtime i18n helper for backend-facing user messages."""

from __future__ import annotations

from typing import Any


def _parse_language(language: str | None) -> str:
    raw = (language or "en").strip().lower()
    if raw.startswith("zh") or raw in {"cn", "chinese"}:
        return "zh"
    if raw.startswith("pt") or raw in {"pt-br", "portuguese", "português"}:
        return "pt"
    if raw.startswith("fr") or raw in {"french", "francais", "français"}:
        return "fr"
    if raw.replace("_", "-").split("-", 1)[0] == "tr" or raw in {"turkish", "türkçe"}:
        return "tr"
    return "en"


_MESSAGES: dict[str, dict[str, str]] = {
    "tr": {
        "api.content_required": "İçerik gereklidir",
        "api.invalid_channels_config": "Geçersiz kanal yapılandırması",
        "api.partner_already_exists": "'{name}' adlı partner zaten var",
        "api.partner_not_found": "Partner bulunamadı",
        "api.partner_not_found_or_not_running": "Partner bulunamadı veya çalışmıyor",
        "api.partner_not_running": "Partner çalışmıyor",
        "api.partner_stopped_start_required": "Partner durdurulmuş. Sohbete başlamadan önce başlatın.",
        "api.persona_already_exists": "Kişilik zaten var: {name}",
        "api.persona_name_required": "Kişilik adı gereklidir",
        "api.persona_not_found": "Kişilik bulunamadı: {name}",
        "api.soul_already_exists": "'{name}' adlı kişilik zaten var",
        "api.soul_content_empty": "Özel kişilik içeriği boş",
        "api.soul_library_not_found": "'{name}' adlı kişilik kitaplıkta bulunamadı",
        "api.soul_not_found": "Kişilik bulunamadı",
        "api.tool_not_found": "'{name}' aracı bulunamadı",
        "cli_apps.abi_mismatch": "{app!r} CLI uygulaması {installed} için kurulmuş, ancak bu çalışma zamanı {current} kullanıyor. Bir yöneticinin uygulamayı yeniden kurması gerekiyor.",
        "cli_apps.args_required": "{tool} bir 'args' dizisi gerektirir — her öğede bir komut satırı argümanı olmalıdır.",
        "cli_apps.entry_admin_only": "CLI uygulamalarını bir yönetici kurar; bu uygulamayı eklemesini yöneticinizden isteyin.",
        "cli_apps.install_in_progress": "Bu uygulama zaten kuruluyor.",
        "cli_apps.not_in_catalog": "Katalogda {id!r} adlı CLI uygulaması yok.",
        "cli_apps.not_installed": "{app!r} CLI uygulaması artık bu dağıtımda kurulu değil.",
        "cli_apps.still_running": "{app} hâlâ çalışıyor ({seconds} sn)",
        "mcp.configure_command_or_url": "{name!r} sunucusu: bir komut (stdio) veya URL yapılandırın.",
        "mcp.configure_before_testing": "Test etmeden önce bir komut (stdio) veya URL yapılandırın.",
        "mcp.server_error": "{name!r} sunucusu: {error}",
        "mcp.server_missing": "Listenizde {name!r} adlı sunucu yok.",
        "mcp.not_oauth": "Bu sunucu OAuth kullanmıyor; bunun yerine kimlik bilgisi girin.",
        "mcp.oauth_callback_incomplete": "Yetkilendirme yanıtı eksikti.",
        "mcp.oauth_callback_unknown": "Bu yetkilendirmenin süresi dolmuş veya zaten tamamlanmış. Yeniden başlatın.",
        "mcp.oauth_done": "Yetkilendirme tamamlandı. Bu sekmeyi kapatabilirsiniz.",
        "mcp.oauth_failed": "Yetkilendirme başarısız oldu.",
        "mcp.catalog_entry_missing": "Katalogda {id!r} adlı MCP hizmeti yok.",
        "mcp.entry_admin_only": "Bu hizmet yerel bir komut olarak çalışır ve yalnızca bir yönetici tarafından eklenebilir.",
        "mcp.tool_not_available": "Bu araç bu sohbette kullanılamıyor. Yalnızca prompt içinde listelenen araçlar çağrılabilir.",
        "sandbox.command_blocked": "Hata: komut güvenlik denetimi tarafından engellendi (tehlikeli kalıp).",
        "sandbox.disabled_for_account": "Hesabınız için kod çalıştırma devre dışı bırakılmış.",
        "sandbox.no_backend": "Kullanılabilir sandbox arka ucu yok",
    },
    "pt": {
        "api.content_required": "o conteúdo é obrigatório",
        "api.invalid_channels_config": "Configuração de canais inválida",
        "api.partner_already_exists": "O parceiro '{name}' já existe",
        "api.partner_not_found": "Parceiro não encontrado",
        "api.partner_not_found_or_not_running": "Parceiro não encontrado ou não está em execução",
        "api.partner_not_running": "Parceiro não está em execução",
        "api.partner_stopped_start_required": "O parceiro está parado. Inicie-o antes de conversar.",
        "api.persona_already_exists": "A persona já existe: {name}",
        "api.persona_name_required": "O nome da persona é obrigatório",
        "api.persona_not_found": "Persona não encontrada: {name}",
        "api.soul_already_exists": "A personalidade '{name}' já existe",
        "api.soul_content_empty": "O conteúdo da personalidade personalizada está vazio",
        "api.soul_library_not_found": "A personalidade '{name}' não foi encontrada na biblioteca",
        "api.soul_not_found": "Personalidade não encontrada",
        "api.tool_not_found": "Ferramenta '{name}' não encontrada",
        "cli_apps.abi_mismatch": "O app de CLI {app!r} foi instalado para {installed}, mas este ambiente é {current}. Um administrador precisa reinstalá-lo.",
        "cli_apps.args_required": "{tool} precisa de uma lista 'args' — um argumento de linha de comando por elemento.",
        "cli_apps.entry_admin_only": "Os aplicativos de linha de comando são instalados por um administrador; peça ao seu administrador para adicionar este.",
        "cli_apps.install_in_progress": "Esse app já está sendo instalado.",
        "cli_apps.not_in_catalog": "Nenhum app de CLI chamado {id!r} no catálogo.",
        "cli_apps.not_installed": "O app de CLI {app!r} não está mais instalado nesta implantação.",
        "cli_apps.still_running": "{app} ainda está em execução ({seconds}s)",
        "mcp.configure_command_or_url": "Servidor {name!r}: configure um comando (stdio) ou uma URL.",
        "mcp.configure_before_testing": "Configure um comando (stdio) ou uma URL antes de testar.",
        "mcp.server_error": "Servidor {name!r}: {error}",
        "mcp.server_missing": "Nenhum servidor chamado {name!r} na sua lista.",
        "mcp.not_oauth": "Este servidor não usa OAuth; forneça uma credencial.",
        "mcp.oauth_callback_incomplete": "A resposta de autorização está incompleta.",
        "mcp.oauth_callback_unknown": "Essa autorização expirou ou já foi concluída. Inicie-a novamente.",
        "mcp.oauth_done": "Autorizado. Você pode fechar esta aba.",
        "mcp.oauth_failed": "Falha na autorização.",
        "mcp.catalog_entry_missing": "Nenhum serviço MCP chamado {id!r} no catálogo.",
        "mcp.entry_admin_only": "Este serviço é executado como um comando local e só pode ser adicionado por um administrador.",
        "mcp.tool_not_available": "Esta ferramenta não está disponível nesta conversa. Apenas as ferramentas listadas no prompt podem ser chamadas.",
        "sandbox.command_blocked": "Erro: comando bloqueado pela proteção de segurança (padrão perigoso).",
        "sandbox.disabled_for_account": "A execução de código está desativada para a sua conta.",
        "sandbox.no_backend": "nenhum backend de ambiente isolado disponível",
    },
    "en": {
        "api.content_required": "content is required",
        "api.invalid_channels_config": "Invalid channels config",
        "api.partner_already_exists": "Partner '{name}' already exists",
        "api.partner_not_found": "Partner not found",
        "api.partner_not_found_or_not_running": "Partner not found or not running",
        "api.partner_not_running": "Partner not running",
        "api.partner_stopped_start_required": "Partner is stopped. Start it before chatting.",
        "api.persona_already_exists": "Persona already exists: {name}",
        "api.persona_name_required": "Persona name is required",
        "api.persona_not_found": "Persona not found: {name}",
        "api.soul_already_exists": "Soul '{name}' already exists",
        "api.soul_content_empty": "Custom soul content is empty",
        "api.soul_library_not_found": "Soul '{name}' not found in library",
        "api.soul_not_found": "Soul not found",
        "api.tool_not_found": "Tool '{name}' not found",
        "cli_apps.abi_mismatch": (
            "The CLI app {app!r} was installed for {installed} but this runtime is "
            "{current}. An administrator needs to reinstall it."
        ),
        "cli_apps.args_required": (
            "{tool} needs an 'args' array — one command-line argument per element."
        ),
        "cli_apps.entry_admin_only": (
            "CLI apps are installed by an administrator; ask yours to add this one."
        ),
        "cli_apps.install_in_progress": "That app is already being installed.",
        "cli_apps.not_in_catalog": "No CLI app named {id!r} in the catalog.",
        "cli_apps.not_installed": (
            "The CLI app {app!r} is not installed on this deployment any more."
        ),
        "cli_apps.still_running": "{app} is still running ({seconds}s)",
        "mcp.configure_command_or_url": "Server {name!r}: configure either a command (stdio) or a url.",
        "mcp.configure_before_testing": "Configure either a command (stdio) or a url before testing.",
        "mcp.server_error": "Server {name!r}: {error}",
        "mcp.server_missing": "No server named {name!r} in your list.",
        "mcp.not_oauth": "This server does not use OAuth; give it a credential instead.",
        "mcp.oauth_callback_incomplete": "The authorization response was incomplete.",
        "mcp.oauth_callback_unknown": "That authorization has expired or already completed. Start it again.",
        "mcp.oauth_done": "Authorized. You can close this tab.",
        "mcp.oauth_failed": "Authorization failed.",
        "mcp.catalog_entry_missing": "No MCP service named {id!r} in the catalog.",
        "mcp.entry_admin_only": (
            "This service runs as a local command and can only be added by an administrator."
        ),
        "mcp.tool_not_available": (
            "This tool is not available in this conversation. "
            "Only the tools listed in the prompt can be called."
        ),
        "sandbox.command_blocked": "Error: command blocked by safety guard (dangerous pattern).",
        "sandbox.disabled_for_account": "Code execution is disabled for your account.",
        "sandbox.no_backend": "no sandbox backend available",
    },
    "zh": {
        "api.content_required": "content 不能为空",
        "api.invalid_channels_config": "渠道配置无效",
        "api.partner_already_exists": "伙伴 '{name}' 已存在",
        "api.partner_not_found": "未找到伙伴",
        "api.partner_not_found_or_not_running": "未找到伙伴或伙伴未运行",
        "api.partner_not_running": "伙伴未运行",
        "api.partner_stopped_start_required": "伙伴已停止。请先启动后再聊天。",
        "api.persona_already_exists": "Persona 已存在：{name}",
        "api.persona_name_required": "Persona 名称不能为空",
        "api.persona_not_found": "未找到 Persona：{name}",
        "api.soul_already_exists": "Soul '{name}' 已存在",
        "api.soul_content_empty": "自定义 soul 内容为空",
        "api.soul_library_not_found": "素材库中未找到 soul '{name}'",
        "api.soul_not_found": "未找到 soul",
        "api.tool_not_found": "未找到工具 '{name}'",
        "cli_apps.abi_mismatch": (
            "CLI 应用 {app!r} 是为 {installed} 安装的，当前运行环境是 {current}，需要管理员重新安装。"
        ),
        "cli_apps.args_required": "{tool} 需要 args 数组：每个命令行参数占一个元素。",
        "cli_apps.entry_admin_only": "CLI 应用由管理员安装，请联系管理员添加。",
        "cli_apps.install_in_progress": "该应用正在安装中。",
        "cli_apps.not_in_catalog": "目录中没有名为 {id!r} 的 CLI 应用。",
        "cli_apps.not_installed": "CLI 应用 {app!r} 已不在本部署中。",
        "cli_apps.still_running": "{app} 仍在运行（已 {seconds} 秒）",
        "mcp.configure_command_or_url": "服务器 {name!r}：请配置 command（stdio）或 url。",
        "mcp.configure_before_testing": "测试前请先配置 command（stdio）或 url。",
        "mcp.server_error": "服务器 {name!r}：{error}",
        "mcp.server_missing": "你的列表中没有名为 {name!r} 的服务器。",
        "mcp.not_oauth": "该服务器不使用 OAuth，请改为填写凭据。",
        "mcp.oauth_callback_incomplete": "授权回调信息不完整。",
        "mcp.oauth_callback_unknown": "该授权已过期或已完成，请重新发起。",
        "mcp.oauth_done": "已授权，可以关闭此页。",
        "mcp.oauth_failed": "授权失败。",
        "mcp.catalog_entry_missing": "目录中没有名为 {id!r} 的 MCP 服务。",
        "mcp.entry_admin_only": "该服务以本地命令方式运行，只能由管理员添加。",
        "mcp.tool_not_available": "该工具在本次对话中不可用，只能调用提示中列出的工具。",
        "sandbox.command_blocked": "错误：命令被安全防护拦截（匹配危险模式）。",
        "sandbox.disabled_for_account": "你的账号已禁用代码执行。",
        "sandbox.no_backend": "没有可用的沙箱后端",
    },
    "fr": {
        "api.content_required": "le contenu est requis",
        "api.invalid_channels_config": "Configuration des canaux invalide",
        "api.partner_already_exists": "Le partenaire « {name} » existe déjà",
        "api.partner_not_found": "Partenaire introuvable",
        "api.partner_not_found_or_not_running": "Partenaire introuvable ou non démarré",
        "api.partner_not_running": "Le partenaire n’est pas démarré",
        "api.partner_stopped_start_required": (
            "Le partenaire est arrêté. Démarrez-le avant de discuter."
        ),
        "api.persona_already_exists": "Le persona existe déjà : {name}",
        "api.persona_name_required": "Le nom du persona est requis",
        "api.persona_not_found": "Persona introuvable : {name}",
        "api.soul_already_exists": "Le soul « {name} » existe déjà",
        "api.soul_content_empty": "Le contenu personnalisé du soul est vide",
        "api.soul_library_not_found": "Soul « {name} » introuvable dans la bibliothèque",
        "api.soul_not_found": "Soul introuvable",
        "api.tool_not_found": "Outil « {name} » introuvable",
        "cli_apps.abi_mismatch": (
            "L’application CLI {app!r} a été installée pour {installed}, mais ce runtime "
            "est {current}. Un administrateur doit la réinstaller."
        ),
        "cli_apps.args_required": (
            "{tool} nécessite un tableau « args » — un argument de ligne de commande par élément."
        ),
        "cli_apps.entry_admin_only": (
            "Les applications CLI sont installées par un administrateur ; "
            "demandez-lui d’ajouter celle-ci."
        ),
        "cli_apps.install_in_progress": "Cette application est déjà en cours d’installation.",
        "cli_apps.not_in_catalog": "Aucune application CLI nommée {id!r} dans le catalogue.",
        "cli_apps.not_installed": (
            "L’application CLI {app!r} n’est plus installée sur ce déploiement."
        ),
        "cli_apps.still_running": "{app} est toujours en cours d’exécution ({seconds} s)",
        "mcp.configure_command_or_url": (
            "Serveur {name!r} : configurez soit une command (stdio), soit une url."
        ),
        "mcp.configure_before_testing": (
            "Configurez une command (stdio) ou une url avant de tester."
        ),
        "mcp.server_error": "Serveur {name!r} : {error}",
        "mcp.server_missing": "Aucun serveur nommé {name!r} dans votre liste.",
        "mcp.not_oauth": ("Ce serveur n’utilise pas OAuth ; fournissez-lui plutôt un identifiant."),
        "mcp.oauth_callback_incomplete": "La réponse d’autorisation est incomplète.",
        "mcp.oauth_callback_unknown": (
            "Cette autorisation a expiré ou est déjà terminée. Recommencez."
        ),
        "mcp.oauth_done": "Autorisé. Vous pouvez fermer cet onglet.",
        "mcp.oauth_failed": "L’autorisation a échoué.",
        "mcp.catalog_entry_missing": "Aucun service MCP nommé {id!r} dans le catalogue.",
        "mcp.entry_admin_only": (
            "Ce service s’exécute comme commande locale et ne peut être ajouté que "
            "par un administrateur."
        ),
        "mcp.tool_not_available": (
            "Cet outil n’est pas disponible dans cette conversation. Seuls les outils "
            "listés dans l’invite peuvent être appelés."
        ),
        "sandbox.command_blocked": (
            "Erreur : commande bloquée par le garde-fou de sécurité (motif dangereux)."
        ),
        "sandbox.disabled_for_account": "L’exécution de code est désactivée pour votre compte.",
        "sandbox.no_backend": "aucun backend de bac à sable disponible",
    },
}


def current_language(default: str = "en") -> str:
    try:
        from deeptutor.services.settings.interface_settings import get_ui_language

        return _parse_language(get_ui_language(default=default))
    except Exception:
        return _parse_language(default)


def t(key: str, default: str = "", *, language: str | None = None, **kwargs: Any) -> str:
    lang = _parse_language(language) if language else current_language()
    text = _MESSAGES.get(lang, {}).get(key) or _MESSAGES["en"].get(key) or default
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


__all__ = ["current_language", "t"]

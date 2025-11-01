import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8012"))

    # CoinGecko (free public API)
    COINGECKO_API_URL = os.getenv("COINGECKO_API_URL", "https://api.coingecko.com/api/v3")
    COINGECKO_TIMEOUT = float(os.getenv("COINGECKO_TIMEOUT", "10"))
    ALIAS_TTL = int(os.getenv("ALIAS_TTL", "3600"))

    # News (RSS via feedparser)
    COINDESK_RSS = os.getenv("COINDESK_RSS", "https://www.coindesk.com/arc/outboundfeeds/rss/")
    RSS2JSON_API_URL = os.getenv("RSS2JSON_API_URL", "https://api.rss2json.com/v1/api.json")

    # Redis
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ENABLED = bool(REDIS_URL)
    CACHE_TTL_SHORT = int(os.getenv("CACHE_TTL_SHORT", "300"))
    CHAT_HISTORY_TTL = int(os.getenv("CHAT_HISTORY_TTL", "86400")) 

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
    AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "200"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

    # Prompts
    PROMPT_DIR = os.getenv("PROMPT_DIR", "app/prompts")
    PROMPT_FILE = os.getenv("PROMPT_FILE", "cryptosage.tpl")
    SOURCE_LABEL = os.getenv("SOURCE_LABEL", "Telex.im A2A")
    DEPLOYMENT_LABEL = os.getenv("DEPLOYMENT_LABEL", "CryptoSage A2A")

    # Agent metadata
    AGENT_NAME = os.getenv("AGENT_NAME", "CryptoSage AI")
    AGENT_DESCRIPTION = os.getenv("AGENT_DESCRIPTION", "Crypto-focused A2A agent: prices, market lists, headlines, and concise explanations.")
    AGENT_VERSION = os.getenv("AGENT_VERSION", "1.0.0")
    AGENT_PUBLISHER = os.getenv("AGENT_PUBLISHER", "Emmanuel Ademola")
    AGENT_WEBSITE = os.getenv("AGENT_WEBSITE", "https://emmanueldev247.github.io/")

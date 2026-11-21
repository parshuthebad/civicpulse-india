import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    REALITY_DEFENDER_API_KEY: str = os.getenv("REALITY_DEFENDER_API_KEY", "").strip()
    SIGHTENGINE_USER: str = os.getenv("SIGHTENGINE_USER", "").strip()
    SIGHTENGINE_SECRET: str = os.getenv("SIGHTENGINE_SECRET", "").strip()
    WALTER_API_KEY: str = os.getenv("WALTER_API_KEY", "").strip()
    RESEMBLE_API_KEY: str = os.getenv("RESEMBLE_API_KEY", "").strip()
    MODULATE_API_KEY: str = os.getenv("MODULATE_API_KEY", "").strip()

    GOOGLE_FACTCHECK_API_KEY: str = (
        os.getenv("GOOGLE_FACT_CHECK_API_KEY", "").strip()
        or os.getenv("GOOGLE_FACTCHECK_API_KEY", "").strip()
    )
    PARALLEL_API_KEY: str = os.getenv("PARALLEL_API_KEY", "").strip()
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "").strip()
    NEWSDATA_API_KEY: str = os.getenv("NEWSDATA_API_KEY", "").strip()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
    HF_TOKEN: str = os.getenv("HF_TOKEN", "").strip()

    ZERO_RETENTION_MODE: bool = os.getenv("ZERO_RETENTION_MODE", "true").lower() == "true"

    def provider_status(self) -> dict:
        return {
            "reality_defender": bool(self.REALITY_DEFENDER_API_KEY),
            "sightengine": bool(self.SIGHTENGINE_USER and self.SIGHTENGINE_SECRET),
            "resemble_ai": bool(self.RESEMBLE_API_KEY),
            "google_factcheck": bool(self.GOOGLE_FACTCHECK_API_KEY),
            "tavily_search": bool(self.TAVILY_API_KEY),
            "newsdata_io": bool(self.NEWSDATA_API_KEY),
            "gemini_llm": bool(self.GEMINI_API_KEY),
            "groq_llm": bool(self.GROQ_API_KEY),
            "gdelt_rss": True,
            "mediawiki_wikipedia": True,
        }

    @property
    def active_count(self) -> int:
        return sum(1 for v in self.provider_status().values() if v)

    @property
    def mode(self) -> str:
        return f"Local-First ({self.active_count}/{len(self.provider_status())} Providers Configured)"


settings = Settings()

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { LibraryArticle, LibraryArticleDetail } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const CATEGORY_LABELS: Record<string, string> = {
  agents: "Агенты",
  mcp: "MCP",
  skills: "Навыки",
  models: "Модели",
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.charAt(0).toUpperCase() + category.slice(1);
}

export function Library() {
  const [articles, setArticles] = useState<LibraryArticle[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryArticleDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<LibraryArticle[]>("/library/articles")
      .then((data) => {
        setArticles(data);
        setSelectedSlug((current) => current ?? data[0]?.slug ?? null);
      })
      .catch((e) => console.error("Failed to load library:", e));
  }, []);

  useEffect(() => {
    if (!selectedSlug) return;
    setLoadingDetail(true);
    api
      .get<LibraryArticleDetail>(`/library/articles/${encodeURI(selectedSlug)}`)
      .then(setDetail)
      .catch((e) => {
        console.error("Failed to load article:", e);
        setDetail(null);
      })
      .finally(() => setLoadingDetail(false));
  }, [selectedSlug]);

  const categories = useMemo(
    () => Array.from(new Set(articles.map((a) => a.category))).sort(),
    [articles]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return articles.filter(
      (a) =>
        (!category || a.category === category) &&
        (!q ||
          a.title.toLowerCase().includes(q) ||
          a.summary.toLowerCase().includes(q) ||
          a.tags.some((t) => t.toLowerCase().includes(q)))
    );
  }, [articles, query, category]);

  return (
    <div>
      <PageHeader
        title="Библиотека знаний"
        description="Материалы по безопасности ИИ — агенты, MCP, навыки и модели. Список собирается из локальных Markdown-файлов."
      />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 340px) 1fr", gap: "2.4rem", alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по материалам"
          />

          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
            {[null, ...categories].map((c) => (
              <button
                key={c ?? "all"}
                type="button"
                className="btn btn-secondary"
                style={{
                  padding: "0.5rem 1.2rem",
                  fontSize: 13,
                  background: category === c ? "var(--background-generic)" : undefined,
                }}
                onClick={() => setCategory(c)}
              >
                {c === null ? "Все" : categoryLabel(c)}
              </button>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {filtered.map((article) => {
              const active = article.slug === selectedSlug;
              return (
                <button
                  key={article.slug}
                  type="button"
                  className="card"
                  onClick={() => setSelectedSlug(article.slug)}
                  style={{
                    textAlign: "left",
                    cursor: "pointer",
                    padding: "1.4rem 1.6rem",
                    borderColor: active ? "var(--brand)" : undefined,
                    boxShadow: active ? "0 0 0 0.1rem var(--brand)" : undefined,
                  }}
                >
                  <div style={{ display: "flex", gap: "0.8rem", alignItems: "center", marginBottom: "0.4rem" }}>
                    <span className="badge badge-neutral">{categoryLabel(article.category)}</span>
                    <span style={{ fontSize: 12, color: "var(--text-400)" }}>{article.date}</span>
                  </div>
                  <div style={{ fontWeight: 600, color: "var(--text-1000)", marginBottom: "0.2rem" }}>
                    {article.title}
                  </div>
                  {article.summary && (
                    <div style={{ fontSize: 13, color: "var(--text-500)", lineHeight: 1.4 }}>
                      {article.summary}
                    </div>
                  )}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="card" style={{ color: "var(--text-500)", fontSize: 13 }}>
                {articles.length === 0
                  ? "Материалов пока нет. Добавьте .md файлы в папку library/."
                  : "Ничего не найдено — измените запрос или категорию."}
              </div>
            )}
          </div>
        </div>

        <div className="card" style={{ minHeight: "40rem" }}>
          {!detail && !loadingDetail && (
            <div className="empty-state">Выберите материал слева, чтобы прочитать.</div>
          )}
          {loadingDetail && !detail && <div style={{ color: "var(--text-500)" }}>Загрузка…</div>}
          {detail && (
            <article>
              <div style={{ display: "flex", gap: "0.8rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.8rem" }}>
                <span className="badge badge-neutral">{categoryLabel(detail.category)}</span>
                <span style={{ fontSize: 12, color: "var(--text-400)" }}>{detail.date}</span>
                {detail.source && <span style={{ fontSize: 12, color: "var(--text-400)" }}>· {detail.source}</span>}
              </div>
              <div className="library-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.content}</ReactMarkdown>
              </div>
              {detail.tags.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "2rem" }}>
                  {detail.tags.map((tag) => (
                    <span key={tag} className="badge badge-neutral">#{tag}</span>
                  ))}
                </div>
              )}
            </article>
          )}
        </div>
      </div>
    </div>
  );
}

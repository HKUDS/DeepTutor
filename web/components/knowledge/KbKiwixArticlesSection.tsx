"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { BookOpen, Loader2, Search } from "lucide-react";
import { importKiwixArticle, searchKiwixArticles, type KiwixArticle } from "@/features/knowledge/api/client";
import { knowledgeBaseRef, type KnowledgeBase } from "@/lib/knowledge-helpers";
import { readingCollectionRoute } from "@/lib/learning-routes";

export default function KbKiwixArticlesSection({ kb }: { kb: KnowledgeBase }) {
  const { t } = useTranslation();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KiwixArticle[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [openingPath, setOpeningPath] = useState("");
  const [error, setError] = useState("");

  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError("");
    setSearched(false);
    try {
      setResults(await searchKiwixArticles(knowledgeBaseRef(kb), query.trim()));
      setSearched(true);
    } catch (cause) {
      setResults([]);
      setError(cause instanceof Error ? cause.message : t("Kiwix search failed"));
    } finally {
      setSearching(false);
    }
  };

  const openArticle = async (article: KiwixArticle) => {
    setOpeningPath(article.article_path);
    setError("");
    try {
      const result = await importKiwixArticle({
        kbRef: knowledgeBaseRef(kb),
        articlePath: article.article_path,
        title: article.title,
      });
      router.push(readingCollectionRoute(result.workspace.workspace_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("Could not open Kiwix article"));
    } finally {
      setOpeningPath("");
    }
  };

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold">{kb.metadata?.zim_title || t("Kiwix archive")}</h2>
        <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
          {t("Search articles in this ZIM. DeepTutor retrieves matches for chat, Book, and Guided Learning without importing the archive.")}
        </p>
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">{kb.metadata?.zim_name}</p>
      </div>
      <form onSubmit={(event) => void search(event)} className="flex gap-2">
        <label className="sr-only" htmlFor="kiwix-article-query">{t("Search articles")}</label>
        <input id="kiwix-article-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search articles")} className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px]" />
        <button type="submit" disabled={!query.trim() || searching} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-[13px] font-medium text-[var(--primary-foreground)] disabled:opacity-50">
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}{t("Search")}
        </button>
      </form>
      {error && <p role="alert" className="text-[12px] text-red-600">{error}</p>}
      {searched && results.length === 0 && <p className="text-[12px] text-[var(--muted-foreground)]">{t("No readable articles found.")}</p>}
      <ul className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)]">
        {results.map((article) => (
          <li key={article.article_path} className="p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[13px] font-medium">{article.title}</p>
                <p className="mt-1 line-clamp-3 text-[11px] text-[var(--muted-foreground)]">{article.excerpt}</p>
              </div>
              <button type="button" disabled={!!openingPath} onClick={() => void openArticle(article)} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[12px] font-medium disabled:opacity-50">
                {openingPath === article.article_path ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookOpen className="h-3.5 w-3.5" />}{t("Read article")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

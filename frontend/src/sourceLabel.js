/**
 * One-line "where did this come from" label, e.g. "Risk Management · Clause 4.2 · p. 7".
 * Skips whatever the backend doesn't know.
 * @param {{section?: string, clause_number?: string, page?: number}|null|undefined} source
 */
export const sourceLabel = (source) => {
    if (!source) return '';
    const parts = [];
    if (source.section && source.section !== 'General') parts.push(source.section);
    if (source.clause_number) parts.push(`Clause ${source.clause_number}`);
    if (source.page != null) parts.push(`p. ${source.page}`);
    return parts.join(' \u00b7 ');
};

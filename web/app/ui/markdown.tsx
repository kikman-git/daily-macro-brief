import React from "react";

/* A deliberately small markdown renderer for dive bodies.
 *
 * It returns React elements, never HTML strings — the input is model-generated, so
 * dangerouslySetInnerHTML would turn any stray <script> in a dive into an injection. Scope is
 * exactly what the macro-dive skill emits: headings, paragraphs, lists, tables, blockquotes,
 * rules, and inline bold/italic/code/links. Anything else degrades to plain text, which is the
 * correct failure mode for a reading surface. */

let key = 0;
const k = () => `md${key++}`;

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string): React.ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((tok) => {
    if (tok.startsWith("**") && tok.endsWith("**")) return <strong key={k()}>{tok.slice(2, -2)}</strong>;
    if (tok.startsWith("`") && tok.endsWith("`")) return <code key={k()}>{tok.slice(1, -1)}</code>;
    if (tok.startsWith("*") && tok.endsWith("*")) return <em key={k()}>{tok.slice(1, -1)}</em>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
    if (link) {
      const href = link[2];
      // Only http(s) survives: a javascript: URL in a citation must not become a live link.
      if (!/^https?:\/\//i.test(href)) return <span key={k()}>{link[1]}</span>;
      return (
        <a key={k()} href={href} target="_blank" rel="noopener noreferrer">
          {link[1]}
        </a>
      );
    }
    return <React.Fragment key={k()}>{tok}</React.Fragment>;
  });
}

const cells = (line: string) =>
  line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const out: React.ReactNode[] = [];
  let para: string[] = [];

  const flush = () => {
    if (para.length) {
      out.push(<p key={k()}>{inline(para.join(" "))}</p>);
      para = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const t = line.trim();

    if (!t) {
      flush();
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      flush();
      out.push(<hr key={k()} />);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(t);
    if (h) {
      flush();
      const Tag = (h[1].length <= 2 ? "h2" : "h3") as "h2" | "h3";
      out.push(<Tag key={k()}>{inline(h[2])}</Tag>);
      continue;
    }
    // table: a header row followed by a |---|---| separator
    if (t.startsWith("|") && /^\|[\s:|-]+\|$/.test((lines[i + 1] ?? "").trim())) {
      flush();
      const head = cells(t);
      const body: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) body.push(cells(lines[i++]));
      i--;
      out.push(
        <div key={k()} className="table-wrap overflow-x-auto">
          <table>
            <thead>
              <tr>{head.map((c) => <th key={k()}>{inline(c)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((row) => (
                <tr key={k()}>{row.map((c) => <td key={k()}>{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    if (t.startsWith(">")) {
      flush();
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        buf.push(lines[i++].trim().replace(/^>\s?/, ""));
      }
      i--;
      out.push(<blockquote key={k()}>{inline(buf.join(" "))}</blockquote>);
      continue;
    }
    const bullet = /^([-*+]|\d+\.)\s+(.*)$/.exec(t);
    if (bullet) {
      flush();
      const ordered = /^\d/.test(bullet[1]);
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^([-*+]|\d+\.)\s+(.*)$/.exec(lines[i].trim());
        if (!m) break;
        let text = m[2];
        i++;
        // fold continuation lines into the item they belong to
        while (i < lines.length && lines[i].trim() && !/^([-*+]|\d+\.|#|>|\|)/.test(lines[i].trim())) {
          text += " " + lines[i++].trim();
        }
        items.push(text);
      }
      i--;
      const List = ordered ? "ol" : "ul";
      out.push(
        <List key={k()}>
          {items.map((it) => (
            <li key={k()}>{inline(it)}</li>
          ))}
        </List>
      );
      continue;
    }
    para.push(t);
  }
  flush();
  return <>{out}</>;
}

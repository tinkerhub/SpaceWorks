import { Card } from "../../../components/ui";
import { CLASSIFICATION_RULES, STANDARD_CATEGORIES, sampleItemCode } from "./categoryStandard";

export function CodeChip({ children }: { children: string }) {
  return <code className="whitespace-nowrap rounded-sm bg-subtle px-1.5 py-0.5 font-mono text-caption text-ink">{children}</code>;
}

/** Renders `MCU`-style spans in a rule as code chips. */
function RuleText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/).map((part, index) =>
        part.startsWith("`") ? <CodeChip key={index}>{part.slice(1, -1)}</CodeChip> : <span key={index}>{part}</span>,
      )}
    </>
  );
}

/** The platform-wide reference: category codes, the classification rules and the item-code format. */
export function CategoryGuide({ prefix }: { prefix?: string }) {
  const example = sampleItemCode(prefix);
  return (
    <Card as="section" aria-labelledby="category-guide-heading">
      <details className="group">
        <summary className="cursor-pointer list-none rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
          <h2 id="category-guide-heading" className="text-title text-ink">Classification guide</h2>
          <p className="mt-1 text-body-ui text-ink-secondary">
            Every item gets a code like <CodeChip>{example}</CodeChip>: makerspace prefix, category code, then a letter.{" "}
            <span className="font-semibold text-accent-ink underline-offset-4 hover:underline group-open:hidden">Show the guide</span>
          </p>
        </summary>
        <div className="mt-5 grid min-w-0 gap-6">
          <section aria-labelledby="category-reference-heading" className="min-w-0">
            <h3 id="category-reference-heading" className="mb-3 text-label text-ink">Component categories</h3>
            <div className="sw-scroll-x">
              <table className="w-full min-w-[640px] border-collapse text-left text-body-ui">
                <thead>
                  <tr className="border-b border-line text-label text-ink">
                    <th scope="col" className="py-2 pr-4">Code</th>
                    <th scope="col" className="py-2 pr-4">Category</th>
                    <th scope="col" className="py-2 pr-4">What goes here</th>
                    <th scope="col" className="py-2">Examples</th>
                  </tr>
                </thead>
                <tbody>
                  {STANDARD_CATEGORIES.map((category) => (
                    <tr key={category.code} className="border-b border-line align-top last:border-0">
                      <td className="py-3 pr-4"><CodeChip>{category.code}</CodeChip></td>
                      <td className="py-3 pr-4 text-ink">{category.name}</td>
                      <td className="py-3 pr-4 text-ink-secondary">{category.scope}</td>
                      <td className="py-3 text-ink-secondary">{category.examples}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section aria-labelledby="category-rules-heading">
            <h3 id="category-rules-heading" className="mb-2 text-label text-ink">Rules for classifying components</h3>
            <p className="mb-2 text-body-ui text-ink-secondary">To keep the inventory consistent, follow these rules:</p>
            <ul className="grid list-disc gap-2 pl-5 text-body-ui text-ink-secondary">
              {CLASSIFICATION_RULES.map((rule) => (
                <li key={rule.title}>
                  <strong className="font-semibold text-ink">{rule.title}</strong> <RuleText text={rule.body} />
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="item-code-format-heading">
            <h3 id="item-code-format-heading" className="mb-2 text-label text-ink">Item code format</h3>
            <p className="text-body-ui text-ink-secondary">
              <CodeChip>{sampleItemCode(prefix, "CATEGORY", "LETTER")}</CodeChip> — letters are given out in order
              (<CodeChip>{sampleItemCode(prefix, "MCU", "A")}</CodeChip>, <CodeChip>{sampleItemCode(prefix, "MCU", "B")}</CodeChip>,{" "}
              <CodeChip>{sampleItemCode(prefix, "SNS", "A")}</CodeChip>) and never reused. Change the prefix in Settings → General.
            </p>
          </section>
        </div>
      </details>
    </Card>
  );
}

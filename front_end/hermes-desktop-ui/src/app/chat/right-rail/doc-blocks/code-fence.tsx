import { CodeCard, CodeCardBody } from '@/components/chat/code-card'
import { exceedsHighlightBudget, LazyShiki, SHIKI_THEME } from '@/components/chat/shiki-highlighter'
import { CopyButton } from '@/components/ui/copy-button'
import { useI18n } from '@/i18n'

/**
 * A fenced code block in a document: small language label, highlighted body,
 * hover-reveal copy. While the fence is still being written the body stays
 * plain text so the highlighter does not re-run on every token.
 */
export function DocCodeFence({ code, language, writing }: { code: string; language?: string; writing?: boolean }) {
  const { t } = useI18n()
  const text = code.replace(/^\n+/, '').trimEnd()

  if (!text.trim()) {
    return null
  }

  const plain = writing || exceedsHighlightBudget(text)

  return (
    <CodeCard className="my-[0.7em] text-[0.85em]" data-language={language || undefined} data-slot="doc-code">
      <div className="flex h-6 items-center px-3 pt-1.5 font-mono text-[0.65rem] leading-none text-muted-foreground">
        <span data-slot="doc-code-language">{language || 'text'}</span>
      </div>
      <CopyButton
        appearance="inline"
        className="absolute right-1.5 top-1.5 z-10 h-5 gap-0 rounded-md px-1 opacity-0 transition-opacity group-hover/code:opacity-100 focus-visible:opacity-100"
        iconClassName="size-2.5"
        label={t.assistant.tool.copyCode}
        showLabel={false}
        text={text}
      />
      <CodeCardBody className="max-h-[28rem] overflow-auto [&_pre]:p-0">
        <div className="overflow-x-auto px-3 pb-2.5 pt-1.5">
          {plain ? (
            <pre className="m-0">
              <code className="block whitespace-pre">{text}</code>
            </pre>
          ) : (
            <LazyShiki
              addDefaultStyles={false}
              as="div"
              defaultColor="light-dark()"
              delay={120}
              language={language || 'text'}
              showLanguage={false}
              theme={SHIKI_THEME}
            >
              {text}
            </LazyShiki>
          )}
        </div>
      </CodeCardBody>
    </CodeCard>
  )
}

import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
})

export function renderMarkdown(value = '') {
  return markdown.render(String(value || ''))
}

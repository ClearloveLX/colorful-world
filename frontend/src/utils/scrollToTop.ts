type ScrollableWindow = Pick<Window, 'scrollTo'>

export function scrollWindowToTop(target: ScrollableWindow = window): void {
  target.scrollTo({ top: 0, behavior: 'smooth' })
}

# docs-next

Docs for qbrix next. Nothing here is published: qbrix.io renders `docs/` only,
and the docs workflow deploys on changes to `docs/` only.

Write a page here when a next change alters behaviour. Behaviour today's product
gets too is documented in `docs/` as usual.

- Pages are `.mdx` with the same frontmatter as `docs/` (`title`, `description`,
  `order`). The order is settled when the pages move.
- Link with `/docs/<slug>`, as the published docs do. A link resolves to a page
  here first, then to one in `docs/`, so pages that stay (self-hosting,
  configuration) are linked, not copied.
- Check them from `web/` with `pnpm check-docs:next`; CI runs it.

The release PR moves every page into `docs/`, replacing the pages they
supersede. This README stays behind.

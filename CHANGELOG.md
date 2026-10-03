# Changelog

## [0.2.1](https://github.com/optiq-io/qbrix/compare/v0.2.0...v0.2.1) (2026-10-03)


### Bug Fixes

* **store:** stream workers set up their consumer group in the retry loop ([#16](https://github.com/optiq-io/qbrix/issues/16)) ([20aec13](https://github.com/optiq-io/qbrix/commit/20aec138d20e890717e67297e4343a4d0e77422e))

## [0.2.0](https://github.com/optiq-io/qbrix/compare/v0.1.0...v0.2.0) (2026-09-27)


### ⚠ BREAKING CHANGES

* **proxy:** /api/v1/ee/insight/* and /api/v1/ee/event/* return 404. Use /api/v1/insight/* and /api/v1/event/*, and upgrade the qbrix MCP server.

### Code Refactoring

* **proxy:** drop the /api/v1/ee analytics aliases ([#11](https://github.com/optiq-io/qbrix/issues/11)) ([7c78893](https://github.com/optiq-io/qbrix/commit/7c78893480110bdfcbc9827e3fb442fe865f9675))

## [0.1.0](https://github.com/optiq-io/qbrix/compare/v0.1.0...v0.1.0) (2026-09-27)


### Features

* first public release ([#2](https://github.com/optiq-io/qbrix/issues/2)) ([2d90197](https://github.com/optiq-io/qbrix/commit/2d90197ffe2ecc374b784f00fe974c7a95cfac9a))

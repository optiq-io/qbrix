# Changelog

## [0.3.0](https://github.com/optiq-io/qbrix/compare/v0.2.0...v0.3.0) (2026-10-24)


### ⚠ BREAKING CHANGES

* PROXY_ANALYTICS_ENABLED, ANALYTICS_ENABLED, QBRIX_ANALYTICS_ENABLED, the compose "analytics" profile, the bin/selfhost-init --analytics flag and the chart's global.analytics.enabled are gone. The proxy needs PROXY_CLICKHOUSE_HOST (Compose and the chart set it). A chart install with infrastructure.clickhouse.enabled=false must set global.clickhouse.host, and an install that ran without analytics gains a ClickHouse StatefulSet with a 20Gi volume on upgrade.

### Features

* **core:** add a Beta Thompson sampling policy that learns from the whole score ([#55](https://github.com/optiq-io/qbrix/issues/55)) ([37ac54b](https://github.com/optiq-io/qbrix/commit/37ac54b23d61dadeeae308aff591dc73c0215cbc))
* **core:** add the Spinoza, Leibniz and Buridan engines, named and versioned ([#56](https://github.com/optiq-io/qbrix/issues/56)) ([503ff83](https://github.com/optiq-io/qbrix/commit/503ff83e554d0e9f699c3c303d6c3334d9837274))
* **core:** add Thompson sampling policies that learn the spread of outcomes ([#54](https://github.com/optiq-io/qbrix/issues/54)) ([e00a3b3](https://github.com/optiq-io/qbrix/commit/e00a3b331274436770e672401432322e9f602aa4))
* **cortex:** count every outcome by how it ended, learned or not and why ([#58](https://github.com/optiq-io/qbrix/issues/58)) ([373b428](https://github.com/optiq-io/qbrix/commit/373b42839d788f89004ead53450efaea6ecb47a4))
* **cortex:** learn each outcome once, with params, count and ack in one transaction ([#47](https://github.com/optiq-io/qbrix/issues/47)) ([4f35e37](https://github.com/optiq-io/qbrix/commit/4f35e3704eb0fef7c0c7b0d57d6b44b845267848))
* **proxy:** add loops, options and cycles, created, launched and renamed as changes, behind the next switch ([#62](https://github.com/optiq-io/qbrix/issues/62)) ([fd2e8f8](https://github.com/optiq-io/qbrix/commit/fd2e8f8679879080e5d65a4f7ff9c31fa390007a))
* **proxy:** add metrics with a semantic, type, window and versions, behind the next switch ([#61](https://github.com/optiq-io/qbrix/issues/61)) ([5671ad3](https://github.com/optiq-io/qbrix/commit/5671ad363491c11f1296d98b6514d4d55895bc83))
* **proxy:** add the next switch, off by default ([#45](https://github.com/optiq-io/qbrix/issues/45)) ([069b24b](https://github.com/optiq-io/qbrix/commit/069b24b378ab31a714e21408acfacff546f5745b))
* **proxy:** count every select call by outcome, and answer an unknown experiment with 404 ([#57](https://github.com/optiq-io/qbrix/issues/57)) ([6121484](https://github.com/optiq-io/qbrix/commit/61214846be1d1d0045a69c0a75ffb39e0e59682f))
* **proxy:** record every write as a change, with who made it, before and after ([#52](https://github.com/optiq-io/qbrix/issues/52)) ([d587be0](https://github.com/optiq-io/qbrix/commit/d587be039caff9e92d14a2844dfdb1c87805053a))
* **proxy:** undo a recorded change as a new change, restoring what was learned ([#53](https://github.com/optiq-io/qbrix/issues/53)) ([338ab70](https://github.com/optiq-io/qbrix/commit/338ab70b948e456d988f3dbc7645f7ddeb436315))
* run analytics on every install ([#51](https://github.com/optiq-io/qbrix/issues/51)) ([af909da](https://github.com/optiq-io/qbrix/commit/af909da5f0faca0ba8824c3dda4bc294600860bc))


### Bug Fixes

* **console:** only follow same-origin paths after sign-in, and keep them through registration ([#44](https://github.com/optiq-io/qbrix/issues/44)) ([42e1b82](https://github.com/optiq-io/qbrix/commit/42e1b8238478d0428d670b9f5d7992d45adab2b9))
* **deps:** bump certifi to 2026.10.19 ([#50](https://github.com/optiq-io/qbrix/issues/50)) ([3648e1b](https://github.com/optiq-io/qbrix/commit/3648e1bec250fbed2f6c219e47a53cd267f5e79e))
* **proxy:** reject feedback whose token was issued to another workspace ([#59](https://github.com/optiq-io/qbrix/issues/59)) ([46ca789](https://github.com/optiq-io/qbrix/commit/46ca789ce5246635c5f866713ced1ac1616332c9))
* **redis:** never evict, persist every second, and size the streams to fit ([#48](https://github.com/optiq-io/qbrix/issues/48)) ([c12a7fa](https://github.com/optiq-io/qbrix/commit/c12a7fae367baaa7d223bdc981758a097b024cda))
* **store:** stream workers set up their consumer group in the retry loop ([#16](https://github.com/optiq-io/qbrix/issues/16)) ([20aec13](https://github.com/optiq-io/qbrix/commit/20aec138d20e890717e67297e4343a4d0e77422e))
* **streams:** trim fanned-out streams to what every group has acked ([#49](https://github.com/optiq-io/qbrix/issues/49)) ([454ccef](https://github.com/optiq-io/qbrix/commit/454ccef18ddbb58c0b13693f9deec5224c7b4705))
* **web:** exclude nested node_modules from the console build context ([#60](https://github.com/optiq-io/qbrix/issues/60)) ([5d0db2d](https://github.com/optiq-io/qbrix/commit/5d0db2db5beba8992828d95a8bd593813da3638a))

## [0.2.0](https://github.com/optiq-io/qbrix/compare/v0.1.0...v0.2.0) (2026-09-27)


### ⚠ BREAKING CHANGES

* **proxy:** /api/v1/ee/insight/* and /api/v1/ee/event/* return 404. Use /api/v1/insight/* and /api/v1/event/*, and upgrade the qbrix MCP server.

### Code Refactoring

* **proxy:** drop the /api/v1/ee analytics aliases ([#11](https://github.com/optiq-io/qbrix/issues/11)) ([7c78893](https://github.com/optiq-io/qbrix/commit/7c78893480110bdfcbc9827e3fb442fe865f9675))

## [0.1.0](https://github.com/optiq-io/qbrix/compare/v0.1.0...v0.1.0) (2026-09-27)


### Features

* first public release ([#2](https://github.com/optiq-io/qbrix/issues/2)) ([2d90197](https://github.com/optiq-io/qbrix/commit/2d90197ffe2ecc374b784f00fe974c7a95cfac9a))

# Changelog

## [0.3.0](https://github.com/optiq-io/qbrix/compare/v0.2.0...v0.3.0) (2026-10-31)


### ⚠ BREAKING CHANGES

* PROXY_ANALYTICS_ENABLED, ANALYTICS_ENABLED, QBRIX_ANALYTICS_ENABLED, the compose "analytics" profile, the bin/selfhost-init --analytics flag and the chart's global.analytics.enabled are gone. The proxy needs PROXY_CLICKHOUSE_HOST (Compose and the chart set it). A chart install with infrastructure.clickhouse.enabled=false must set global.clickhouse.host, and an install that ran without analytics gains a ClickHouse StatefulSet with a 20Gi volume on upgrade.

### Features

* **console:** add the next console's four-part header ([#91](https://github.com/optiq-io/qbrix/issues/91)) ([6e84611](https://github.com/optiq-io/qbrix/commit/6e846114d85f202cc7c43ac48d450dcf94bc7fc7))
* **console:** add the next console's shell under /next, behind a build flag ([#86](https://github.com/optiq-io/qbrix/issues/86)) ([95900fc](https://github.com/optiq-io/qbrix/commit/95900fc2d06316ca34a3ce49ec67872ebad55716))
* **console:** add the next console's tokens, light and dark, beside today's ([#81](https://github.com/optiq-io/qbrix/issues/81)) ([a958879](https://github.com/optiq-io/qbrix/commit/a958879c7a5e77337c3aa861f17451e8e884b791))
* **console:** pin loops and metrics per person in the next console ([#92](https://github.com/optiq-io/qbrix/issues/92)) ([d4092fd](https://github.com/optiq-io/qbrix/commit/d4092fd143c3b7e5932e11b6cbaeaeb3d90568d5))
* **console:** serve the connection approval page at /authorize, so a client can finish signing in ([#84](https://github.com/optiq-io/qbrix/issues/84)) ([97c3889](https://github.com/optiq-io/qbrix/commit/97c388946274231ea6e68e37cdcc4b4807d8e516))
* **core:** add a Beta Thompson sampling policy that learns from the whole score ([#55](https://github.com/optiq-io/qbrix/issues/55)) ([37ac54b](https://github.com/optiq-io/qbrix/commit/37ac54b23d61dadeeae308aff591dc73c0215cbc))
* **core:** add the Spinoza, Leibniz and Buridan engines, named and versioned ([#56](https://github.com/optiq-io/qbrix/issues/56)) ([503ff83](https://github.com/optiq-io/qbrix/commit/503ff83e554d0e9f699c3c303d6c3334d9837274))
* **core:** add Thompson sampling policies that learn the spread of outcomes ([#54](https://github.com/optiq-io/qbrix/issues/54)) ([e00a3b3](https://github.com/optiq-io/qbrix/commit/e00a3b331274436770e672401432322e9f602aa4))
* **cortex:** count every outcome by how it ended, learned or not and why ([#58](https://github.com/optiq-io/qbrix/issues/58)) ([373b428](https://github.com/optiq-io/qbrix/commit/373b42839d788f89004ead53450efaea6ecb47a4))
* **cortex:** learn each outcome once, with params, count and ack in one transaction ([#47](https://github.com/optiq-io/qbrix/issues/47)) ([4f35e37](https://github.com/optiq-io/qbrix/commit/4f35e3704eb0fef7c0c7b0d57d6b44b845267848))
* **cortex:** seal decisions from the ledger by their window and learn from sealed decisions only ([#66](https://github.com/optiq-io/qbrix/issues/66)) ([8e7e2b6](https://github.com/optiq-io/qbrix/commit/8e7e2b65ee905485d16187ed4c77c6ddd7af15b8))
* **proxy:** accept outcome(request_id, value) as a metric event for one decision, behind the next switch ([#65](https://github.com/optiq-io/qbrix/issues/65)) ([182887a](https://github.com/optiq-io/qbrix/commit/182887adfeead0f703395ecdc1295ab649e5b561))
* **proxy:** add loops, options and cycles, created, launched and renamed as changes, behind the next switch ([#62](https://github.com/optiq-io/qbrix/issues/62)) ([fd2e8f8](https://github.com/optiq-io/qbrix/commit/fd2e8f8679879080e5d65a4f7ff9c31fa390007a))
* **proxy:** add metrics with a semantic, type, window and versions, behind the next switch ([#61](https://github.com/optiq-io/qbrix/issues/61)) ([5671ad3](https://github.com/optiq-io/qbrix/commit/5671ad363491c11f1296d98b6514d4d55895bc83))
* **proxy:** add the next switch, off by default ([#45](https://github.com/optiq-io/qbrix/issues/45)) ([069b24b](https://github.com/optiq-io/qbrix/commit/069b24b378ab31a714e21408acfacff546f5745b))
* **proxy:** count every select call by outcome, and answer an unknown experiment with 404 ([#57](https://github.com/optiq-io/qbrix/issues/57)) ([6121484](https://github.com/optiq-io/qbrix/commit/61214846be1d1d0045a69c0a75ffb39e0e59682f))
* **proxy:** give each mcp connection its own limit, 120 calls a minute of which at most 30 changes ([#77](https://github.com/optiq-io/qbrix/issues/77)) ([6c13ebd](https://github.com/optiq-io/qbrix/commit/6c13ebd104c519e99e6f6604eaa2a4e51a155770))
* **proxy:** pause a live loop when qbrix fails its decisions, as a change made by qbrix, behind the next switch ([#78](https://github.com/optiq-io/qbrix/issues/78)) ([118574f](https://github.com/optiq-io/qbrix/commit/118574f942acf6667bf890fb350d95a5ddca47f7))
* **proxy:** read loops over the API: get, list with each loop's latest change, cycles and history, behind the next switch ([#70](https://github.com/optiq-io/qbrix/issues/70)) ([f8471f7](https://github.com/optiq-io/qbrix/commit/f8471f794a2391297e2c8beaf949685d63315290))
* **proxy:** record every write as a change, with who made it, before and after ([#52](https://github.com/optiq-io/qbrix/issues/52)) ([d587be0](https://github.com/optiq-io/qbrix/commit/d587be039caff9e92d14a2844dfdb1c87805053a))
* **proxy:** resume a paused loop as a change a person makes, behind the next switch ([#72](https://github.com/optiq-io/qbrix/issues/72)) ([372219e](https://github.com/optiq-io/qbrix/commit/372219ee64ed1177aa29619fa400a25ad7bb6443))
* **proxy:** serve a loop's results from the ledger: share, waiting, lift and health, behind the next switch ([#71](https://github.com/optiq-io/qbrix/issues/71)) ([9f95420](https://github.com/optiq-io/qbrix/commit/9f954209f01c64e74581f5dd80813b0f713ab822))
* **proxy:** serve qbrix's MCP server at /mcp with the skeleton tools, behind the next switch ([#75](https://github.com/optiq-io/qbrix/issues/75)) ([ec9d28d](https://github.com/optiq-io/qbrix/commit/ec9d28d243c8ca89daf8723409874c7d7448b95f))
* **proxy:** serve select(loop, context) with an option, a request_id and a reason, behind the next switch ([#64](https://github.com/optiq-io/qbrix/issues/64)) ([d5514f9](https://github.com/optiq-io/qbrix/commit/d5514f92401b46af35109e9e59353ea26d9f4a6f))
* **proxy:** show why and when a loop paused, with its evidence in history, the loops list and one loop's read ([#80](https://github.com/optiq-io/qbrix/issues/80)) ([b0ce4fc](https://github.com/optiq-io/qbrix/commit/b0ce4fc988907d9debd7bc000435fb548c9e8945))
* **proxy:** sign connections in with OAuth 2.1, qbrix as its own authorization server, behind the next switch ([#73](https://github.com/optiq-io/qbrix/issues/73)) ([6cae619](https://github.com/optiq-io/qbrix/commit/6cae6197705057ac1127e74b9eb8262ed99ceab1))
* **proxy:** undo a recorded change as a new change, restoring what was learned ([#53](https://github.com/optiq-io/qbrix/issues/53)) ([338ab70](https://github.com/optiq-io/qbrix/commit/338ab70b948e456d988f3dbc7645f7ddeb436315))
* run analytics on every install ([#51](https://github.com/optiq-io/qbrix/issues/51)) ([af909da](https://github.com/optiq-io/qbrix/commit/af909da5f0faca0ba8824c3dda4bc294600860bc))
* **ui:** add the next console's controls and overlays: buttons, fields, menus, hover cards, dialogs, sheets and toasts ([#85](https://github.com/optiq-io/qbrix/issues/85)) ([fd2e6f4](https://github.com/optiq-io/qbrix/commit/fd2e6f43c975448406fcf08403f7d3be9133618a))
* **ui:** add the next console's empty, loading and error states: empty, skeletons, not found, couldn't load, offline and larger screen ([#87](https://github.com/optiq-io/qbrix/issues/87)) ([3382714](https://github.com/optiq-io/qbrix/commit/3382714e9b25e5bb636d6dab0e365e7d8c838d8f))
* **ui:** add the next console's entity forms and object page, list, change and health modules ([#88](https://github.com/optiq-io/qbrix/issues/88)) ([08253a5](https://github.com/optiq-io/qbrix/commit/08253a5b18210483aac46d6c2a736d51a15c86ec))
* **ui:** add the next console's share of decisions chart and living numbers ([#90](https://github.com/optiq-io/qbrix/issues/90)) ([66eaf4e](https://github.com/optiq-io/qbrix/commit/66eaf4eb1e29f947e0399a2a4e58cb95ba0f07ef))
* **ui:** add the next console's time rail and stream modules ([#89](https://github.com/optiq-io/qbrix/issues/89)) ([301b6b1](https://github.com/optiq-io/qbrix/commit/301b6b1cb081712e57043f6fc166fdac64879573))


### Bug Fixes

* **console:** bump next to 15.5.28 for the image optimizer advisory ([#82](https://github.com/optiq-io/qbrix/issues/82)) ([005e784](https://github.com/optiq-io/qbrix/commit/005e7845905a1f9abf7f19f8b35f46e008544630))
* **console:** only follow same-origin paths after sign-in, and keep them through registration ([#44](https://github.com/optiq-io/qbrix/issues/44)) ([42e1b82](https://github.com/optiq-io/qbrix/commit/42e1b8238478d0428d670b9f5d7992d45adab2b9))
* **deps:** bump certifi to 2026.10.19 ([#50](https://github.com/optiq-io/qbrix/issues/50)) ([3648e1b](https://github.com/optiq-io/qbrix/commit/3648e1bec250fbed2f6c219e47a53cd267f5e79e))
* **deps:** bump pyasn1 and record the dnspython scan exception ([#93](https://github.com/optiq-io/qbrix/issues/93)) ([81d0ecb](https://github.com/optiq-io/qbrix/commit/81d0ecb0df0785e45a516e3ba3eb5432617c2198))
* **docker:** upgrade openssl in the service images ahead of the base image ([#67](https://github.com/optiq-io/qbrix/issues/67)) ([71942bb](https://github.com/optiq-io/qbrix/commit/71942bb363edbc237d4c51a1ea79680abf933616))
* **proxy:** reconnect to motor and cortex within seconds of them coming back ([#79](https://github.com/optiq-io/qbrix/issues/79)) ([b12533e](https://github.com/optiq-io/qbrix/commit/b12533e5fbb3eccaa0d3dcfc61ba8d3f0d7d99c3))
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

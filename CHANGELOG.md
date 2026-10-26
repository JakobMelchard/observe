# Changelog

## [0.2.4](https://github.com/JakobMelchard/observe/compare/v0.2.3...v0.2.4) (2026-10-26)


### Documentation

* pin install tags to v0.2.3 ([#86](https://github.com/JakobMelchard/observe/issues/86)) ([b08d10f](https://github.com/JakobMelchard/observe/commit/b08d10f9cfbc831221c9300ce40f1c748625935b))

## [0.2.3](https://github.com/JakobMelchard/observe/compare/v0.2.2...v0.2.3) (2026-10-16)


### Documentation

* pin install tags to v0.2.2 ([#81](https://github.com/JakobMelchard/observe/issues/81)) ([2ccf9a4](https://github.com/JakobMelchard/observe/commit/2ccf9a4eaad0f1f25849ab5bb898ef0ba0fd0577))

## [0.2.2](https://github.com/JakobMelchard/observe/compare/v0.2.1...v0.2.2) (2026-10-15)


### Documentation

* **github:** spell unparsable in expiry comment ([#79](https://github.com/JakobMelchard/observe/issues/79)) ([fe4f4f5](https://github.com/JakobMelchard/observe/commit/fe4f4f55fd37805f76a689b06ace71eb9319d434))

## [0.2.1](https://github.com/JakobMelchard/observe/compare/v0.2.0...v0.2.1) (2026-10-15)


### Bug Fixes

* **config:** read pyproject.toml settings from [tool.observe] ([#46](https://github.com/JakobMelchard/observe/issues/46)) ([678d982](https://github.com/JakobMelchard/observe/commit/678d982e6b7f806556d3fbe6277b859e2cef22c6))
* **core:** never inject the shim ahead of the doctype ([#49](https://github.com/JakobMelchard/observe/issues/49)) ([cb636d6](https://github.com/JakobMelchard/observe/commit/cb636d6cc657348083d0af486d592d1a1c92a124))
* **core:** refuse non-browser feedback and cap feedback per day ([#63](https://github.com/JakobMelchard/observe/issues/63)) ([b8f30fc](https://github.com/JakobMelchard/observe/commit/b8f30fce561480f913de7840ba7d198f75261051))
* **github:** render an unusable log timestamp as ? ([#50](https://github.com/JakobMelchard/observe/issues/50)) ([22cde9c](https://github.com/JakobMelchard/observe/commit/22cde9c0d961614b95cae5b9ba194e24dc5ff6f8))
* **http_server:** inject only into 2xx HTML responses ([#67](https://github.com/JakobMelchard/observe/issues/67)) ([2fcecd8](https://github.com/JakobMelchard/observe/commit/2fcecd8f6e47cc55f1d2dc1e13f2b509289ec497))
* **http_server:** stream non-HTML responses instead of buffering them ([#44](https://github.com/JakobMelchard/observe/issues/44)) ([b8e9ba2](https://github.com/JakobMelchard/observe/commit/b8e9ba2c36ac495d58062c23bc0c874ab5d50da5))
* keep client text out of issue titles and bound the delivery queue ([#64](https://github.com/JakobMelchard/observe/issues/64)) ([21f3865](https://github.com/JakobMelchard/observe/commit/21f38651e6ffd9e0c3ac920981ecb5aed57faf2a))
* **otlp:** skip attributes whose key is not a string ([#59](https://github.com/JakobMelchard/observe/issues/59)) ([ed73b59](https://github.com/JakobMelchard/observe/commit/ed73b5919e11bb4d980549823cc3f6fa5d7f757c))
* **otlp:** skip malformed payload parts instead of raising ([#43](https://github.com/JakobMelchard/observe/issues/43)) ([f3688e7](https://github.com/JakobMelchard/observe/commit/f3688e77300f5a45075269c7c18e9adc954e1ac5))
* **receiver:** drop an OTLP intValue that overflows int() ([#57](https://github.com/JakobMelchard/observe/issues/57)) ([7d6e6ba](https://github.com/JakobMelchard/observe/commit/7d6e6baa9ee76434ac62154a95ac9d8f63180d2a))


### Documentation

* say that collector.endpoint only moves the browser side ([#48](https://github.com/JakobMelchard/observe/issues/48)) ([d932e86](https://github.com/JakobMelchard/observe/commit/d932e86d7b27f77b11550efa3fd53673c31acde7))
* trim AGENTS.md to rules, drop stale skill notes ([#54](https://github.com/JakobMelchard/observe/issues/54)) ([0e05009](https://github.com/JakobMelchard/observe/commit/0e05009e8b08c1125580a6160e1f332999e12e3f))

## [0.2.0](https://github.com/JakobMelchard/observe/compare/v0.1.1...v0.2.0) (2026-10-11)


### Miscellaneous Chores

* release 0.2.0 ([e42bf09](https://github.com/JakobMelchard/observe/commit/e42bf09c292e0bd3dbe1876b455fe04fdb59b917))

## [0.1.1](https://github.com/JakobMelchard/observe/compare/v0.1.0...v0.1.1) (2026-10-11)


### Features

* **config:** button option to drop the floating trigger ([#22](https://github.com/JakobMelchard/observe/issues/22)) ([62bb497](https://github.com/JakobMelchard/observe/commit/62bb497fec91dc61bf38b5251c7773b9729cd64c))
* **github:** accept App credentials as arguments, not only from the environment ([7b595f6](https://github.com/JakobMelchard/observe/commit/7b595f634b6959b9f851eb8da91d6e6b69903831))
* **github:** authenticate as a GitHub App ([8370bfd](https://github.com/JakobMelchard/observe/commit/8370bfd3bf1d3547c4416fe63b4731fdccf9ee60))
* **middleware:** add http.server handler patcher for raw HTTP servers ([11c1b76](https://github.com/JakobMelchard/observe/commit/11c1b7682b11600969f31e71c45359a2b93ab482))
* **observe:** deployment-agnostic observability sidecar ([455d34e](https://github.com/JakobMelchard/observe/commit/455d34eb2675f9b7d64b65ee3abdc0d24cce0462))
* **sentry:** add decoupled Sentry sink with e2e shape tests ([e86916e](https://github.com/JakobMelchard/observe/commit/e86916e6bda0ac70125ad8ef417bc7f4b7ac239e))
* **shim:** collect a category and a name with feedback ([23460c0](https://github.com/JakobMelchard/observe/commit/23460c0f0d98d11e983a72b72a09d34571140fda))
* **shim:** register the service worker only on request, importable observe.sw.js, lockstep release ([#31](https://github.com/JakobMelchard/observe/issues/31)) ([d218bc7](https://github.com/JakobMelchard/observe/commit/d218bc7f4d3d95d98a9ef1e50d70873e9f100401))
* **shim:** remote feedback endpoint with bearer token for static sites ([#12](https://github.com/JakobMelchard/observe/issues/12)) ([2975d9a](https://github.com/JakobMelchard/observe/commit/2975d9aefc95a9ee57d4e3f649a06387a45fbe2e))


### Bug Fixes

* **core:** limit body size, origin and rate on the POST endpoints ([#17](https://github.com/JakobMelchard/observe/issues/17)) ([f0a2f71](https://github.com/JakobMelchard/observe/commit/f0a2f71f5b98a651b4b28d4da100fd05a7bd810a))
* **core:** set the config before loading the shim ([4222f9f](https://github.com/JakobMelchard/observe/commit/4222f9fccaf2344d2f3a217e416d77a7ff1c6e1f))
* **core:** stop treating &lt;header&gt; fragments as full documents ([#10](https://github.com/JakobMelchard/observe/issues/10)) ([7407c40](https://github.com/JakobMelchard/observe/commit/7407c4027dbfcabab8d898e66c9158c7b4ce79c5))
* **github:** fence untrusted feedback text in issue bodies ([#5](https://github.com/JakobMelchard/observe/issues/5)) ([b6caccc](https://github.com/JakobMelchard/observe/commit/b6caccce2a68c0b7a16977686f0a6024c41d9bfc))
* **go:** htmx/export-safe injection, file sink, OTLP parse ([bec8e64](https://github.com/JakobMelchard/observe/commit/bec8e64af1909b943444a3b380b9adaaa6c0696d))
* **http-server:** buffer wfile output for HTML injection in raw http.server handlers ([3fe9863](https://github.com/JakobMelchard/observe/commit/3fe9863cb78ae84ed0c80d078e60665bd7f01385))
* **http-server:** correct _is_observe_post signature from 3 to 2 params ([d1de7b0](https://github.com/JakobMelchard/observe/commit/d1de7b0acb3f08255ffa2b1fac853b9e2b546d3d))
* never inject the shim into HTML fragments ([c832979](https://github.com/JakobMelchard/observe/commit/c83297912c8d11905db6630fe440af3c92b20852))
* **router:** deliver to sinks off the request thread ([795358e](https://github.com/JakobMelchard/observe/commit/795358e7594d094584ea14a2e71ea389bbe5b6fe))
* **sentry:** stop forwarding feedback, the SDK has no API for it ([#24](https://github.com/JakobMelchard/observe/issues/24)) ([61d688b](https://github.com/JakobMelchard/observe/commit/61d688b02da92de3dca183a63f31c7739cda0e18))
* **shim:** floating trigger always visible ([#23](https://github.com/JakobMelchard/observe/issues/23)) ([a8b1b0b](https://github.com/JakobMelchard/observe/commit/a8b1b0b569e7109c031af9bdd69ded6366b36fa6))
* **shim:** wait for &lt;body&gt; before building the feedback button ([a32891f](https://github.com/JakobMelchard/observe/commit/a32891f5c04bc8c12487ff2593c7d3b08fbf9d07))
* use importlib.resources for shim file access, add package-data config ([d54d6f7](https://github.com/JakobMelchard/observe/commit/d54d6f73f67d6de04752d6806446561b81b39e83))
* WSGI Content-Length, shim resend loop, queue flush, streaming ([#16](https://github.com/JakobMelchard/observe/issues/16)) ([b274af1](https://github.com/JakobMelchard/observe/commit/b274af1b52d3b8546c6627adc8abea953f8ec895))


### Documentation

* **agents:** move AGENTS.md to repo root ([1666cdc](https://github.com/JakobMelchard/observe/commit/1666cdc6036fd17f8fe796bfd384b0ffe59f851c))
* **agents:** move AGENTS.md to repo root so tools load it ([f2ce7cf](https://github.com/JakobMelchard/observe/commit/f2ce7cfd2c283151a6b15f815ef67a65ae6ab742))

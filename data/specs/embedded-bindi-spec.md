---
title: Embedded bindi spec
author: Clarence Claymore
category: specs
updated_at: 2026-06-29T10:00:00Z
---

# Embedded bindi spec

Oh, oh yeah the bindis! Oh, there's bindis everywhere! Oh, embedded in the skin!

This document describes how bindis are embedded into the skin layer. Each bindi carries metadata that RAGFlow can index for retrieval.

## Fields

- **id** — stable document identifier
- **body** — full text content served to RAGFlow
- **updated_at** — used for incremental sync polling

<script setup lang="ts">
import { Toaster } from '~/components/ui/sonner'
import TelemetryConsentDialog from '~/components/TelemetryConsentDialog.vue'
</script>

<template>
  <div>
    <NuxtRouteAnnouncer />
    <NuxtLayout>
      <NuxtPage keepalive />
    </NuxtLayout>
    <TelemetryConsentDialog />
    <Toaster />
  </div>
</template>

<template>
  <div class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 mx-2">
    <!-- Header -->
    <div
      class="flex items-start justify-between gap-3 p-4 cursor-pointer select-none"
      @click="expanded = !expanded"
    >
      <div class="flex gap-3">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-white border border-outline-gray-2"
        >
          <span class="lucide-webhook size-5 text-ink-gray-7" aria-hidden="true" />
        </div>
        <div class="flex flex-col gap-0.5">
          <div class="flex items-center gap-2">
            <span class="text-p-base-medium text-ink-gray-8">
              {{ __('Other Platforms (Webhook)') }}
            </span>
            <Badge theme="green" size="sm">{{ __('Any source') }}</Badge>
          </div>
          <p class="text-p-sm text-ink-gray-6 max-w-xl">
            {{
              __(
                'Capture leads from Google, Meta, LinkedIn, TikTok, web forms and more by connecting through Zapier, Make, or any webhook.',
              )
            }}
          </p>
        </div>
      </div>
      <span
        class="size-4 mt-1 text-ink-gray-5 shrink-0"
        :class="expanded ? 'lucide-chevron-up' : 'lucide-chevron-down'"
        aria-hidden="true"
      />
    </div>

    <!-- Body -->
    <div v-if="expanded" class="border-t border-outline-gray-2 p-4 flex flex-col gap-4">
      <!-- Not permitted -->
      <div
        v-if="config.error"
        class="text-p-sm text-ink-gray-6 flex items-center gap-2"
      >
        <span class="lucide-lock size-4" aria-hidden="true" />
        {{ __('Webhook setup is available to administrators only.') }}
      </div>

      <template v-else>
        <!-- Endpoint URL -->
        <div class="flex flex-col gap-1.5">
          <label class="text-p-sm text-ink-gray-7 font-medium">{{ __('Webhook URL') }}</label>
          <div class="flex items-center gap-2">
            <div
              class="flex-1 truncate rounded-md border border-outline-gray-2 bg-surface-white px-3 py-1.5 text-p-sm text-ink-gray-8 font-mono"
            >
              {{ webhookUrl }}
            </div>
            <Button :label="copied.url ? __('Copied') : __('Copy')" @click="copy('url', webhookUrl)" />
          </div>
        </div>

        <!-- Secret token -->
        <div class="flex flex-col gap-1.5">
          <label class="text-p-sm text-ink-gray-7 font-medium">
            {{ __('Secret Token') }}
            <span class="text-ink-gray-5 font-normal">
              — {{ __('send as header') }} <span class="font-mono">{{ config.data?.header }}</span>
            </span>
          </label>
          <div class="flex items-center gap-2">
            <div
              class="flex-1 truncate rounded-md border border-outline-gray-2 bg-surface-white px-3 py-1.5 text-p-sm text-ink-gray-8 font-mono"
            >
              {{ revealed ? token : maskedToken }}
            </div>
            <Button :label="revealed ? __('Hide') : __('Show')" @click="revealed = !revealed" />
            <Button :label="copied.token ? __('Copied') : __('Copy')" @click="copy('token', token)" />
            <Button
              :label="__('Regenerate')"
              theme="red"
              variant="subtle"
              :loading="regen.loading"
              @click="regenerate"
            />
          </div>
          <p class="text-p-sm text-ink-gray-5">
            {{ __('Keep this secret. Anyone with it can create leads. Regenerating invalidates the old token.') }}
          </p>
        </div>

        <!-- Steps -->
        <div class="flex flex-col gap-2 rounded-md bg-surface-white border border-outline-gray-2 p-3">
          <div class="text-p-sm text-ink-gray-7 font-medium">{{ __('How to connect (Zapier / Make)') }}</div>
          <ol class="list-decimal ml-4 flex flex-col gap-1 text-p-sm text-ink-gray-7">
            <li>{{ __('In your ad platform (Google, Meta, LinkedIn, TikTok…) connect its "new lead" trigger to Zapier or Make.') }}</li>
            <li>
              {{ __('Add a "Webhooks → POST" action. Set the URL to the Webhook URL above.') }}
            </li>
            <li>
              {{ __('Add a request header') }}
              <span class="font-mono">{{ config.data?.header }}</span>
              {{ __('with the Secret Token as its value.') }}
            </li>
            <li>
              {{ __('Map the lead fields into the JSON body. Supported keys:') }}
              <span class="font-mono text-ink-gray-6">first_name, last_name, email, mobile_no, organization, job_title, website, message</span>
            </li>
            <li>{{ __('Turn the Zap/Scenario on — new leads will appear in the CRM automatically.') }}</li>
          </ol>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { Button, Badge, createResource, toast } from 'frappe-ui'
import { ref, computed, reactive } from 'vue'

const expanded = ref(false)
const revealed = ref(false)
const copied = reactive({ url: false, token: false })

const config = createResource({
  url: 'ai_crm.api.get_lead_webhook_config',
  auto: true,
})

const regen = createResource({
  url: 'ai_crm.api.regenerate_lead_webhook_token',
  onSuccess: (data) => {
    config.setData(data)
    revealed.value = true
    toast.success(__('New token generated'))
  },
  onError: () => toast.error(__('Could not regenerate token')),
})

const token = computed(() => config.data?.token || '')
const maskedToken = computed(() =>
  token.value ? '•'.repeat(Math.min(token.value.length, 40)) : '',
)
const webhookUrl = computed(() =>
  config.data?.path ? window.location.origin + config.data.path : '',
)

function copy(key, value) {
  if (!value) return
  navigator.clipboard?.writeText(value)
  copied[key] = true
  toast.success(__('Copied to clipboard'))
  setTimeout(() => (copied[key] = false), 1500)
}

function regenerate() {
  regen.submit()
}
</script>

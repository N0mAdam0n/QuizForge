export default defineNuxtPlugin(async () => {
  const route = useRoute()

  const { fetchUser, user, token } = useAuth()

  if (token.value && !user.value) {
    await fetchUser()
  }
})

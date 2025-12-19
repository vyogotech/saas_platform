<script setup>
const form = reactive({
  email: '',
  company: '',
  password: '',
  subdomain: ''
})

const register = async () => {
  const res = await fetch('/api/method/saas_platform.api.register_user', {
    method: 'POST',
    body: JSON.stringify(form)
  });
  const result = await res.json();
  if (result.message.success) {
    alert('Tenant is provisioning...');
  }
}
</script>
<template>
  <div class="container">
    <h1>Register</h1>
    <form @submit.prevent="register">
      <div class="form-group">
        <label for="email">Email</label>
        <input type="email" v-model="form.email" required />
      </div>
      <div class="form-group">
        <label for="company">Company Name</label>
        <input type="text" v-model="form.company" required />
      </div>      
      <div class="form-group">
        <label for="subdomain">Subdomain</label>
        <input type="text" v-model="form.subdomain" required />
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" v-model="form.password" required />
      </div>
      <button type="submit">Register</button>
    </form>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>
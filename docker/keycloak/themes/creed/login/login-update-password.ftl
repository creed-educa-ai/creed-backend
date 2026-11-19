<#--
  Definir a senha. É a página do link do convite e da redefinição de senha: o back
  manda o mesmo e-mail nos dois casos (send_update_password_email), então o texto
  serve aos dois.

  Mesmos campos, nomes e regras do login-update-password.ftl do `base` (o Keycloak
  lê "password-new", "password-confirm" e "logout-sessions"). Muda só a marcação,
  que segue o LoginView do front: rótulo, campo com o olho dentro, erro embaixo.
-->
<#import "template.ftl" as layout>
<#import "password-commons.ftl" as passwordCommons>
<#-- O aviso "Você precisa mudar sua senha" (tipo warning) repete o título e, no
     convite, nem é verdade: a pessoa ainda não tem senha. Ele sai; o resto que o
     `base` mostra aqui (erro que não é de campo) continua. -->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('password','password-confirm') && !(message?has_content && message.type = 'warning'); section>
    <#if section = "header">
        ${msg("updatePasswordTitle")}
    <#elseif section = "creedSubtitulo">
        <p class="creed-subtitulo">
            <#if auth?has_content && auth.showUsername()>
                ${msg("creedSubtituloSenhaComEmail", auth.attemptedUsername)}
            <#else>
                ${msg("creedSubtituloSenha")}
            </#if>
        </p>
    <#elseif section = "form">
        <form id="kc-passwd-update-form" class="${properties.kcFormClass!}" action="${url.loginAction}" method="post">
            <@campoSenha
                id="password-new"
                rotulo=msg("passwordNew")
                placeholder=msg("creedSenhaNovaPlaceholder")
                erroDoCampo="password"
                invalido=messagesPerField.existsError('password','password-confirm')
                autofocus=true/>

            <@campoSenha
                id="password-confirm"
                rotulo=msg("passwordConfirm")
                placeholder=msg("creedSenhaConfirmacaoPlaceholder")
                erroDoCampo="password-confirm"
                invalido=messagesPerField.existsError('password-confirm')/>

            <@passwordCommons.logoutOtherSessions/>

            <div id="kc-form-buttons" class="${properties.kcFormButtonsClass!}">
                <#if isAppInitiatedAction??>
                    <button class="${properties.kcButtonClass!} ${properties.kcButtonPrimaryClass!} ${properties.kcButtonBlockClass!}" type="submit">${msg("creedSalvarSenha")}</button>
                    <button class="${properties.kcButtonClass!} ${properties.kcButtonDefaultClass!} ${properties.kcButtonBlockClass!}" type="submit" name="cancel-aia" value="true">${msg("doCancel")}</button>
                <#else>
                    <button class="${properties.kcButtonClass!} ${properties.kcButtonPrimaryClass!} ${properties.kcButtonBlockClass!}" type="submit">${msg("creedSalvarSenha")}</button>
                </#if>
            </div>
        </form>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    </#if>
</@layout.registrationLayout>

<#-- Um campo de senha: Field + FieldLabel + InputGroup com o olho + FieldError do
     front. `erroDoCampo` é o nome que o Keycloak usa para o erro ("password" para o
     primeiro campo, mesmo ele se chamando "password-new"). Só o primeiro campo leva
     a regra de tamanho, quando a política do realm tem uma. -->
<#macro campoSenha id rotulo placeholder erroDoCampo invalido autofocus=false>
    <div class="${properties.kcFormGroupClass!}"<#if invalido> data-invalid="true"</#if>>
        <label for="${id}" class="${properties.kcLabelClass!}">${rotulo}</label>
        <div class="${properties.kcInputGroup!}" dir="ltr">
            <input type="password" id="${id}" name="${id}" class="${properties.kcInputClass!}"
                   placeholder="${placeholder}" autocomplete="new-password"<#if autofocus> autofocus</#if>
                   <#if invalido>aria-invalid="true"</#if>
                   <#if messagesPerField.existsError(erroDoCampo)>aria-describedby="input-error-${erroDoCampo}"</#if>>
            <div class="creed-input-addon">
                <button class="${properties.kcFormPasswordVisibilityButtonClass!}" type="button" aria-label="${msg('showPassword')}"
                        aria-controls="${id}" data-password-toggle
                        data-icon-show="${properties.kcFormPasswordVisibilityIconShow!}" data-icon-hide="${properties.kcFormPasswordVisibilityIconHide!}"
                        data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                    <i class="${properties.kcFormPasswordVisibilityIconShow!}" aria-hidden="true"></i>
                </button>
            </div>
        </div>
        <#if messagesPerField.existsError(erroDoCampo)>
            <div id="input-error-${erroDoCampo}" class="${properties.kcInputErrorMessageClass!}" aria-live="polite">
                ${kcSanitize(messagesPerField.get(erroDoCampo))?no_esc}
            </div>
        <#elseif id = "password-new" && (passwordPolicies.length)??>
            <p class="creed-descricao-campo">${msg("creedSenhaMinimo", passwordPolicies.length)}</p>
        </#if>
    </div>
</#macro>

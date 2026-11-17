<#--
  Página de aviso. No fluxo do CREED ela aparece duas vezes:
  - ao abrir o link do e-mail, pedindo confirmação antes de definir a senha
    (`actionUri` + `requiredActions`);
  - depois de salvar a senha, com o link de volta ao login do front
    (`pageRedirectUri`, o redirect_uri que o back manda no e-mail, P-051).

  Mesmas variáveis e mesma ordem de decisão do info.ftl do `base`. Muda a marcação:
  o link vira o botão primário do front, e cada caso ganha título e texto próprios.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        <#if messageHeader??>
            ${kcSanitize(msg("${messageHeader}"))?no_esc}
        <#elseif actionUri?has_content && requiredActions??>
            ${msg("creedConfirmarAcaoTitulo")}
        <#else>
            ${message.summary}
        </#if>
    <#elseif section = "creedSubtitulo">
        <#-- O texto do aviso só desce para cá quando o título não é ele. -->
        <#if messageHeader?? || (actionUri?has_content && requiredActions??)>
            <p id="kc-info-message" class="creed-subtitulo">
                ${message.summary}<#if requiredActions??><#list requiredActions>: <strong><#items as acao>${kcSanitize(msg("requiredAction.${acao}"))?no_esc}<#sep>, </#items></strong>.</#list></#if>
            </p>
        <#elseif requiredActions??>
            <p id="kc-info-message" class="creed-subtitulo">
                <#list requiredActions as acao>${kcSanitize(msg("requiredAction.${acao}"))?no_esc}<#sep>, </#list>
            </p>
        <#elseif pageRedirectUri?has_content>
            <p id="kc-info-message" class="creed-subtitulo">${msg("creedContaAtualizadaTexto")}</p>
        </#if>
    <#elseif section = "form">
        <#if !skipLink??>
            <#if pageRedirectUri?has_content>
                <div class="creed-acoes-pagina">
                    <a class="creed-botao creed-botao-primario creed-botao-bloco" href="${pageRedirectUri}">${msg("creedIrParaLogin")}</a>
                </div>
            <#elseif actionUri?has_content>
                <div class="creed-acoes-pagina">
                    <a class="creed-botao creed-botao-primario creed-botao-bloco" href="${actionUri}">${msg("proceedWithAction")}</a>
                </div>
            <#elseif (client.baseUrl)?has_content>
                <div class="creed-acoes-pagina">
                    <a class="creed-botao creed-botao-primario creed-botao-bloco" href="${client.baseUrl}">${msg("backToApplication")}</a>
                </div>
            </#if>
        </#if>
    </#if>
</@layout.registrationLayout>

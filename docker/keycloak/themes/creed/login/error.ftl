<#--
  Página de erro. No fluxo do CREED, a que mais aparece é a do link vencido ou já
  usado: o link do e-mail vale uma vez e por tempo limitado (P-049).

  O `base` só oferece "voltar para o aplicativo" quando o client tem `baseUrl`, e o
  creed-backend não tem: a pessoa ficava sem saída. Aqui, com o endereço do front
  (creedFrontendUrl, no theme.properties), ela ganha o caminho que resolve: pedir
  outro link pela redefinição de senha do front, que manda o mesmo e-mail do
  convite. Sem o endereço, a página fica só com o texto.
-->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        ${kcSanitize(msg("errorTitle"))?no_esc}
    <#elseif section = "creedSubtitulo">
        <p id="kc-error-message" class="creed-subtitulo">${kcSanitize(message.summary)?no_esc}</p>
    <#elseif section = "form">
        <#if !skipLink??>
            <#if properties.creedFrontendUrl?has_content>
                <div class="creed-acoes-pagina">
                    <a class="creed-botao creed-botao-primario creed-botao-bloco" href="${properties.creedFrontendUrl}/reset-password">${msg("creedPedirNovoLink")}</a>
                    <a class="creed-botao creed-botao-contorno creed-botao-bloco" href="${properties.creedFrontendUrl}/login">${msg("creedIrParaLogin")}</a>
                </div>
            <#elseif client?? && client.baseUrl?has_content>
                <div class="creed-acoes-pagina">
                    <a id="backToApplication" class="creed-botao creed-botao-primario creed-botao-bloco" href="${client.baseUrl}">${msg("backToApplication")}</a>
                </div>
            </#if>
        </#if>
    </#if>
</@layout.registrationLayout>

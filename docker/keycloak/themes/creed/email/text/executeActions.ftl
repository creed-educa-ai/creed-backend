<#ftl output_format="plainText">
<#--
  A versão em texto do mesmo e-mail (html/executeActions.ftl): o Keycloak manda as
  duas, e o cliente que não mostra HTML mostra esta. Mesmos textos, sem o botão.
-->
<#assign requiredActionsText><#if requiredActions??><#list requiredActions><#items as reqActionItem>${msg("requiredAction.${reqActionItem}")}<#sep>, </#items></#list></#if></#assign>
<#assign soSenha = requiredActions?? && requiredActions?size == 1 && requiredActions[0] == "UPDATE_PASSWORD">
<#-- Mesmo motivo do html/template.ftl: "CREED.ai" solto vira link para outro site. -->
<#assign nome = realmName?replace(".", ".\x200B")>
${msg(soSenha?then("creedEmailSenhaTitulo", "creedEmailAcoesTitulo"))}

<#if soSenha>${msg("creedEmailSenhaTexto", nome)}<#else>${msg("creedEmailAcoesTexto", nome, requiredActionsText)}</#if>

${link}

${msg("creedEmailValidade", linkExpirationFormatter(linkExpiration))}

${msg("creedEmailIgnorar")}

--
${msg("creedEmailRodape", nome)}
